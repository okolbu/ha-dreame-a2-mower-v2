# Greenfield F1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the new `ha-dreame-a2-mower-v2` GitHub repo with a working HA integration that installs, connects to a Dreame A2 (g2408), and exposes the mower's lawn_mower platform entity, battery level, and charging status. This is the minimum-viable installable artifact that subsequent phases (F2–F7) extend.

**Architecture:** Three-layer stack per spec §3 — pure-Python `protocol/` (lifted wholesale from legacy), typed `mower/` domain layer (written fresh against the protocol-doc), HA platform glue (modern coordinator + lawn_mower + 2 sensors). No `homeassistant.*` imports below the top layer.

**Tech Stack:** Python 3.13, Home Assistant 2025.x, pytest, pytest-homeassistant-custom-component, paho-mqtt, requests, Pillow, numpy.

**Spec:** `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md` § 7 phase F1.

**Working discipline:** Per spec §8 carryover — push to `origin/main` after each phase completes. Commits are small, frequent, traceable. The new repo can be temporarily not-installable during F1 build; first installable state is the F1 final commit.

**Repo strategy:** New GitHub repo `okolbu/ha-dreame-a2-mower-v2` (renamed to `okolbu/ha-dreame-a2-mower` at end of F7 cutover after legacy is renamed to `-legacy`). Local clone at `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`.

---

## File map

All paths relative to `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`.

```
ha-dreame-a2-mower-v2/
├── .gitignore                                  # F1.0
├── LICENSE                                     # F1.0 (MIT, fresh)
├── README.md                                   # F1.0 minimal, F1.6 final
├── pyproject.toml                              # F1.0
├── hacs.json                                   # F1.6
├── CONTRIBUTING.md                             # F1.6 — secrets warning section
├── custom_components/
│   └── dreame_a2_mower/
│       ├── __init__.py                         # F1.3 — async_setup_entry
│       ├── manifest.json                       # F1.3
│       ├── const.py                            # F1.3 — domain, log prefixes
│       ├── config_flow.py                      # F1.3 — creds + country
│       ├── coordinator.py                      # F1.4 — DataUpdateCoordinator[MowerState]
│       ├── lawn_mower.py                       # F1.5 — platform entity
│       ├── sensor.py                           # F1.5 — battery_level + charging_status
│       ├── strings.json                        # F1.6 minimal
│       ├── translations/en.json                # F1.6 minimal
│       └── mower/                              # F1.2 — domain layer
│           ├── __init__.py
│           ├── state.py                        # F1.2.1 — MowerState dataclass
│           ├── capabilities.py                 # F1.2.2 — frozen g2408 constants
│           ├── property_mapping.py             # F1.2.3 — (siid,piid) → field_name
│           └── error_codes.py                  # F1.2.4 — apk fault index
├── protocol/                                   # F1.1 — lifted from legacy
│   ├── __init__.py
│   ├── telemetry.py
│   ├── heartbeat.py
│   ├── config_s2p51.py
│   ├── session_summary.py
│   ├── pcd.py
│   ├── pcd_render.py
│   ├── trail_overlay.py
│   ├── cloud_map_geom.py
│   ├── cfg_action.py
│   ├── pose.py
│   ├── replay.py
│   ├── unknown_watchdog.py
│   ├── api_log.py
│   ├── mqtt_archive.py
│   ├── properties_g2408.py
│   └── _jsonable.py
├── docs/
│   ├── research/                               # F1.0 — copied verbatim from legacy
│   │   ├── g2408-protocol.md
│   │   ├── cloud-map-geometry.md
│   │   ├── 2026-04-17-g2408-property-divergences.md
│   │   ├── 2026-04-23-iobroker-dreame-cross-reference.md
│   │   └── webgl-lidar-card-feasibility.md
│   ├── superpowers/
│   │   ├── specs/                              # F1.0 — copied from legacy
│   │   │   └── 2026-04-27-greenfield-integration-design.md
│   │   └── plans/                              # F1.0 — copied from legacy
│   │       └── 2026-04-27-greenfield-f1-foundation.md
│   ├── data-policy.md                          # F1.2 — persistent/volatile/computed split
│   └── lessons-from-legacy.md                  # F1.0 — empty stub, populated lazily
└── tests/
    ├── conftest.py                             # F1.4 — HA pytest fixtures
    ├── protocol/                               # F1.1 — lifted from legacy
    │   └── test_*.py
    ├── mower/                                  # F1.2 — fresh
    │   ├── test_state.py
    │   ├── test_capabilities.py
    │   ├── test_property_mapping.py
    │   └── test_error_codes.py
    └── integration/                            # F1.5 — fresh
        ├── test_setup.py
        └── test_lawn_mower.py
```

---

## Phase F1.0 — Repo bootstrap

### Task F1.0.1: Create new GitHub repo + local clone

**Files:**
- Create (remote): GitHub repo `okolbu/ha-dreame-a2-mower-v2`
- Create (local): `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`

- [ ] **Step 1: Confirm with user before creating remote repo**

Creating a public GitHub repo is a one-shot action. Before running `gh repo create`, confirm with the user:
- Visibility: public (matches legacy) — confirm.
- Repo name: `ha-dreame-a2-mower-v2` for now, will rename at cutover. Confirm.

If the user declines, STOP and report BLOCKED with the user's preferred name/visibility.

- [ ] **Step 2: Create the repo**

Run from `/data/claude/homeassistant/`:

```bash
gh repo create okolbu/ha-dreame-a2-mower-v2 \
  --public \
  --description "Dreame A2 (g2408) lawn mower Home Assistant integration — greenfield, written from scratch (NOT a fork)" \
  --clone
```

Expected: a new directory `ha-dreame-a2-mower-v2/` is created with an empty git repo connected to `origin = okolbu/ha-dreame-a2-mower-v2`.

If the repo already exists (perhaps from a prior attempt), STOP and report — don't overwrite.

- [ ] **Step 3: Verify clone**

```bash
ls -la /data/claude/homeassistant/ha-dreame-a2-mower-v2/.git
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ remote -v
```

Expected: `.git/` directory exists; `origin` points at the new repo.

### Task F1.0.2: Initial scaffold — LICENSE, .gitignore, README stub, pyproject.toml

**Files:**
- Create: `ha-dreame-a2-mower-v2/LICENSE`
- Create: `ha-dreame-a2-mower-v2/.gitignore`
- Create: `ha-dreame-a2-mower-v2/README.md`
- Create: `ha-dreame-a2-mower-v2/pyproject.toml`

Working directory for all subsequent tasks: `/data/claude/homeassistant/ha-dreame-a2-mower-v2/` unless noted.

- [ ] **Step 1: Write LICENSE (MIT)**

Create `LICENSE` with the standard MIT text. Copy verbatim from the legacy repo's `LICENSE` and update the year/copyright holder if necessary:

```
cp /data/claude/homeassistant/ha-dreame-a2-mower/LICENSE LICENSE
```

Open `LICENSE` and verify the copyright line reads `Copyright (c) 2026 okolbu` (or the user's preferred form). Adjust if needed.

- [ ] **Step 2: Write .gitignore**

Create `.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
ENV/
.eggs/
*.egg-info/
*.egg
build/
dist/

# Test artifacts
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
.coverage.*
coverage.xml
*.cover
.hypothesis/
.tox/

# Editor
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Secrets (BELT AND BRACES — never commit credentials)
*credentials*
*.env
.env
secrets.yaml
*.pem
*.key

# Local archives (these belong in <ha_config>/dreame_a2_mower/, not the repo)
sessions/
lidar/
mqtt_archive/
```

- [ ] **Step 3: Write README stub**

Create `README.md`:

```markdown
# Dreame A2 Mower — Home Assistant Integration

> **Status:** Pre-alpha rebuild. The legacy integration at
> [`ha-dreame-a2-mower`](https://github.com/okolbu/ha-dreame-a2-mower)
> remains the working reference until this rebuild reaches feature
> parity. **Do not install yet.**

This is a from-scratch Home Assistant integration for the Dreame A2
(`dreame.mower.g2408`) robotic lawn mower. It is **not a fork** of any
upstream project. Architecture and roadmap are documented at
[`docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`](docs/superpowers/specs/2026-04-27-greenfield-integration-design.md).

## Why a new integration?

The previous integration was a fork of an upstream Dreame vacuum +
multi-mower codebase. Three weeks of reverse-engineering the A2 surfaced
that the A2 shares too little with other Dreame devices for the
multi-model scaffolding to add value. This rebuild keeps only the
g2408-specific code (the wire-codec library and the protocol research)
and reimplements the rest with current HA best practices.

## License

MIT — see `LICENSE`.
```

- [ ] **Step 4: Write pyproject.toml**

Create `pyproject.toml`:

```toml
[project]
name = "ha-dreame-a2-mower"
version = "0.1.0a0"
description = "Home Assistant integration for the Dreame A2 (g2408) robotic lawn mower"
readme = "README.md"
license = { file = "LICENSE" }
authors = [{ name = "okolbu" }]
requires-python = ">=3.13"

[project.urls]
Homepage = "https://github.com/okolbu/ha-dreame-a2-mower-v2"
Issues = "https://github.com/okolbu/ha-dreame-a2-mower-v2/issues"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "I",   # isort
    "B",   # bugbear
    "UP",  # pyupgrade
    "SIM", # simplify
    "RUF", # ruff-specific
]
ignore = []

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E501"]   # tests can have long lines

[tool.mypy]
python_version = "3.13"
strict = true
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true
disallow_untyped_defs = true
check_untyped_defs = true

[[tool.mypy.overrides]]
module = "homeassistant.*"
ignore_missing_imports = true
```

- [ ] **Step 5: Initial commit**

```bash
git add LICENSE .gitignore README.md pyproject.toml
git commit -m "$(cat <<'EOF'
F1.0.2: initial scaffold — LICENSE, .gitignore, README stub, pyproject.toml

Bootstraps the greenfield ha-dreame-a2-mower-v2 repo. LICENSE is MIT
(carried from legacy). .gitignore covers Python build artifacts plus
explicit credential / archive-directory exclusions per spec §5.9.
README labels the repo as pre-alpha and points users at the legacy
repo for now.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin main
```

### Task F1.0.3: Copy docs from legacy

**Files:**
- Create directory: `docs/research/`
- Copy: legacy `docs/research/*.md` → here
- Create directory: `docs/superpowers/specs/`, `docs/superpowers/plans/`
- Copy: this plan + the greenfield spec from legacy
- Create: `docs/lessons-from-legacy.md` (empty stub)

- [ ] **Step 1: Copy research docs**

```bash
mkdir -p docs/research
cp /data/claude/homeassistant/ha-dreame-a2-mower/docs/research/*.md docs/research/
ls docs/research/
```

Expected: 5 files — `g2408-protocol.md`, `cloud-map-geometry.md`, `2026-04-17-g2408-property-divergences.md`, `2026-04-23-iobroker-dreame-cross-reference.md`, `webgl-lidar-card-feasibility.md`.

- [ ] **Step 2: Copy spec + this plan**

```bash
mkdir -p docs/superpowers/specs docs/superpowers/plans
cp /data/claude/homeassistant/ha-dreame-a2-mower/docs/superpowers/specs/2026-04-27-greenfield-integration-design.md docs/superpowers/specs/
cp /data/claude/homeassistant/ha-dreame-a2-mower/docs/superpowers/plans/2026-04-27-greenfield-f1-foundation.md docs/superpowers/plans/
```

- [ ] **Step 3: Create lessons-from-legacy stub**

Create `docs/lessons-from-legacy.md`:

```markdown
# Lessons from the legacy integration

Edge-case handlers, debugging insights, and protocol-doc evidence
extracted from `ha-dreame-a2-mower` (the legacy repo) as the planner
encounters them during the F1–F7 rebuild. Each entry cites the legacy
file:line plus a one-line rationale.

This doc is populated lazily — entries appear here when an implementer
cribs a non-obvious behavior from legacy code, never preemptively.

## Entries

(none yet — F1 implementation in progress)
```

- [ ] **Step 4: Create data-policy stub**

Create `docs/data-policy.md`:

```markdown
# Data policy — persistent / volatile / computed

Per spec §8, every `MowerState` field has a documented unknowns
policy. This doc is the index, kept in sync with the source-of-truth
docstrings in `custom_components/dreame_a2_mower/mower/state.py`.

## Persistent fields (RestoreEntity, last-known across HA boot)

(populated in F1.2.1 onward as fields are added)

## Volatile fields (unavailable when source is None)

(populated in F1.2.1 onward)

## Computed fields (inherits source's policy)

(populated in F1.2.1 onward)
```

- [ ] **Step 5: Commit and push**

```bash
git add docs/
git commit -m "$(cat <<'EOF'
F1.0.3: copy research docs + spec/plan + add policy stubs

Brings docs/research/ over from legacy verbatim — all five .md files.
Copies the greenfield spec and F1 plan from legacy. Adds two empty
stubs: docs/lessons-from-legacy.md (populated lazily as edge cases
get cribbed from legacy) and docs/data-policy.md (populated as
MowerState fields get added in F1.2 onward).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Phase F1.1 — Lift `protocol/` package

### Task F1.1.1: Copy protocol/ tree wholesale

**Files:**
- Create directory: `protocol/` (sibling of `custom_components/`)
- Copy: legacy `custom_components/dreame_a2_mower/protocol/*.py` → here

The legacy `protocol/` package is HA-independent (per architecture audit). Copy verbatim, then verify no HA leaks slipped in.

- [ ] **Step 1: Copy files**

```bash
mkdir -p protocol
cp /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/protocol/*.py protocol/
ls protocol/
```

Expected: 17 .py files matching the legacy `protocol/` listing.

- [ ] **Step 2: Verify no homeassistant imports**

```bash
grep -rn "import homeassistant\|from homeassistant" protocol/ | head -10
```

Expected: zero matches. If any match, that module needs a cleanup pass — STOP, report what you found, and the controller decides whether to clean inline or defer.

- [ ] **Step 3: Verify the package is importable as a top-level package**

The legacy import path was `custom_components.dreame_a2_mower.protocol.X`. The new layout makes it just `protocol.X`. Adjust any relative imports inside the package files:

```bash
grep -rn "from \.\.\|from custom_components" protocol/
```

Expected: relative imports between protocol/ modules are fine (`from .telemetry import ...`); imports referencing `custom_components.*` need rewriting. For each match, change `from custom_components.dreame_a2_mower.protocol.X` to `from .X` (relative within the package).

- [ ] **Step 4: Smoke-test import**

```bash
python3 -c "import protocol; from protocol import telemetry, heartbeat, config_s2p51, session_summary, pcd, trail_overlay; print('ok')"
```

Expected: `ok`. Any `ImportError` means a relative-import fix-up was missed in step 3.

- [ ] **Step 5: Commit**

```bash
git add protocol/
git commit -m "$(cat <<'EOF'
F1.1.1: lift protocol/ package wholesale from legacy

Copies the 17-module pure-Python wire-codec package from legacy
verbatim. Per spec §3 layer 1: no homeassistant imports anywhere
in this layer; tests run in a vanilla pytest venv.

Adjusted any relative-import path differences between the legacy
nested location (custom_components/.../protocol/) and the new
top-level location (protocol/). No code logic changes.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.1.2: Lift protocol/ tests + verify all pass

**Files:**
- Create directory: `tests/protocol/`
- Copy: legacy `tests/protocol/*.py` → here
- Create: `tests/conftest.py` (minimal — pytest config)
- Create: `tests/__init__.py`, `tests/protocol/__init__.py` (empty)

- [ ] **Step 1: Copy test files**

```bash
mkdir -p tests/protocol
cp /data/claude/homeassistant/ha-dreame-a2-mower/tests/protocol/*.py tests/protocol/
touch tests/__init__.py tests/protocol/__init__.py
ls tests/protocol/
```

Expected: 18 test files matching legacy + the empty `__init__.py`.

- [ ] **Step 2: Adjust test imports**

The legacy tests imported the protocol package as `custom_components.dreame_a2_mower.protocol`. In the new layout, it's just `protocol`. Run:

```bash
grep -rn "custom_components\.dreame_a2_mower\.protocol\|from custom_components" tests/protocol/
```

For each match, rewrite to use the bare `protocol` package. Concretely:

```bash
find tests/protocol -name "*.py" -exec sed -i \
    -e 's|custom_components\.dreame_a2_mower\.protocol|protocol|g' \
    -e 's|from custom_components\.dreame_a2_mower\.protocol|from protocol|g' \
    {} +
```

Then verify:

```bash
grep -rn "custom_components" tests/protocol/
```

Expected: zero matches.

- [ ] **Step 3: Create minimal conftest.py**

Create `tests/conftest.py`:

```python
"""Pytest configuration shared by protocol/ + mower/ + integration/ tests.

Per spec §3, the protocol/ + mower/ test suites must run in a vanilla
pytest venv (no Home Assistant required). The integration/ test suite
adds pytest-homeassistant-custom-component fixtures separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the top-level protocol/ package importable in tests
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 4: Run all protocol tests, expect green**

```bash
pytest tests/protocol/ -v
```

Expected: every test passes. Legacy baseline (per recent commit 6888898) had pre-existing failures in `test_trail_overlay.py` due to an `ImportError` from a relative import — those failures must NOT carry forward. If a test fails with `ImportError`, fix the import and re-run.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "$(cat <<'EOF'
F1.1.2: lift protocol/ tests; all green

Copies the 18 protocol-decoder tests from legacy verbatim. Adjusts
imports for the new top-level protocol/ package layout (legacy:
custom_components.dreame_a2_mower.protocol → new: protocol).

This commit also resolves the pre-existing trail_overlay ImportError
that was the only failing test in the legacy suite — the relative
import that failed in legacy works correctly now that protocol/ is
top-level.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Phase F1.2 — Build `mower/` domain layer

### Task F1.2.1: MowerState dataclass — F1 minimal fields

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/__init__.py` (empty)
- Create: `custom_components/dreame_a2_mower/mower/state.py`
- Create: `tests/mower/__init__.py` (empty)
- Create: `tests/mower/test_state.py`

F1 only needs three fields on `MowerState`: `state`, `battery_level`, `charging_status`. The dataclass shape is established here so F2 can add fields incrementally without re-architecting.

- [ ] **Step 1: Create directories**

```bash
mkdir -p custom_components/dreame_a2_mower/mower
mkdir -p tests/mower
touch custom_components/dreame_a2_mower/mower/__init__.py
touch tests/mower/__init__.py
touch custom_components/dreame_a2_mower/__init__.py  # so the integration package itself imports
```

(The full `custom_components/dreame_a2_mower/__init__.py` body is written in F1.3.1 — for now the empty file lets imports resolve.)

- [ ] **Step 2: Write the failing test**

Create `tests/mower/test_state.py`:

```python
"""Regression tests for MowerState — the typed domain model."""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)


def test_mower_state_defaults_are_unknown():
    """Fresh MowerState has unknown values — represents 'no data yet'."""
    s = MowerState()
    assert s.state is None
    assert s.battery_level is None
    assert s.charging_status is None


def test_state_enum_covers_g2408_apk_values():
    """The State enum must include every value the apk decompilation
    documents on g2408 per protocol-doc §2.1."""
    expected = {1, 2, 3, 5, 6, 11, 13, 14}
    actual = {s.value for s in State}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_charging_status_enum_covers_g2408_values():
    """ChargingStatus enum covers the {0, 1, 2} range observed on g2408."""
    expected = {0, 1, 2}
    actual = {c.value for c in ChargingStatus}
    assert expected == actual


def test_mower_state_with_all_fields_set():
    """MowerState supports keyword-only construction with all fields."""
    s = MowerState(
        state=State.WORKING,
        battery_level=72,
        charging_status=ChargingStatus.NOT_CHARGING,
    )
    assert s.state == State.WORKING
    assert s.battery_level == 72
    assert s.charging_status == ChargingStatus.NOT_CHARGING
```

- [ ] **Step 3: Run test, expect FAIL**

```bash
pytest tests/mower/test_state.py -v
```

Expected: ImportError or ModuleNotFoundError on `from custom_components.dreame_a2_mower.mower.state import ...` — the file doesn't exist yet.

- [ ] **Step 4: Implement state.py**

Create `custom_components/dreame_a2_mower/mower/state.py`:

```python
"""Typed domain model for the Dreame A2 (g2408) mower.

Per spec §3 layer 2: this module imports nothing from
``homeassistant.*``. It is the bridge between the pure-Python protocol
codecs (in ``protocol/``) and the HA platform glue (in
``custom_components/dreame_a2_mower/``).

Per spec §8, every field on ``MowerState`` declares its authoritative
source via docstring + a §2.1 citation. Fields default to ``None``
(meaning: no data observed yet).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class State(IntEnum):
    """Mower state per s2.1.

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.1``,
    confirmed via ioBroker apk decompilation.

    Persistence: volatile (HA shows ``unavailable`` when stale).
    """

    WORKING = 1
    STANDBY = 2
    PAUSED = 3
    RETURNING = 5
    CHARGING = 6
    MAPPING = 11
    CHARGED = 13
    UPDATING = 14


class ChargingStatus(IntEnum):
    """Charging status per s3.2 (g2408 enum offset vs upstream).

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s3.2``.

    Persistence: volatile.
    """

    NOT_CHARGING = 0
    CHARGING = 1
    CHARGED = 2


@dataclass(slots=True)
class MowerState:
    """The integration's typed view of the mower's current state.

    Each field's authoritative source and unknowns policy is documented
    on the field itself. Fields default to ``None`` until the first
    fresh data arrives from MQTT or the cloud API.

    Subsequent F2..F7 phases extend this dataclass with additional
    fields. New fields MUST default to ``None`` and MUST cite their
    source per spec §8.
    """

    # Source: s2.1 (confirmed). Persistence: volatile.
    state: State | None = None

    # Source: s3.1 (confirmed). Range 0..100. Persistence: volatile.
    battery_level: int | None = None

    # Source: s3.2 (confirmed, g2408 enum offset). Persistence: volatile.
    charging_status: ChargingStatus | None = None
```

- [ ] **Step 5: Run test, expect PASS**

```bash
pytest tests/mower/test_state.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Update data-policy.md**

Open `docs/data-policy.md`. Under the "Volatile fields" section, add:

```markdown
- `state` — s2.1 (apk-confirmed enum)
- `battery_level` — s3.1
- `charging_status` — s3.2 (g2408 enum offset)
```

Leave Persistent and Computed sections empty for now (F2 onward will populate).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/ tests/mower/ docs/data-policy.md
git commit -m "$(cat <<'EOF'
F1.2.1: MowerState dataclass with F1-minimal fields (state, battery, charging)

Establishes the typed domain layer per spec §3 layer 2. No
homeassistant imports. Three fields suffice for F1 (lawn_mower
platform + battery + charging_status entities); subsequent phases
extend the dataclass.

State enum copies the apk-confirmed values from protocol-doc §2.1
row s2.1 (1=Working, 2=Standby, 3=Paused, 5=Returning, 6=Charging,
11=Mapping, 13=Charged, 14=Updating). ChargingStatus follows the
g2408-overlay {0, 1, 2} mapping.

Each field's docstring cites its §2.1 source and persistence policy
per spec §8. data-policy.md updated.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.2.2: Capabilities frozen constants (lifted from P1.4 snapshot)

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/capabilities.py`
- Create: `tests/mower/test_capabilities.py`

The g2408 capability snapshot from P1.4 is the authoritative source.

- [ ] **Step 1: Write the failing test**

Create `tests/mower/test_capabilities.py`:

```python
"""g2408 capability constants — locks the snapshot from P1.4."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.capabilities import (
    CAPABILITIES,
    Capabilities,
)


def test_capabilities_is_frozen():
    """Capabilities is a frozen dataclass — values cannot be mutated."""
    import dataclasses
    assert dataclasses.is_dataclass(CAPABILITIES)
    # Frozen instance — assignment raises FrozenInstanceError
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        CAPABILITIES.lidar_navigation = False  # type: ignore[misc]


def test_capabilities_g2408_snapshot():
    """The CAPABILITIES singleton matches the P1.4 snapshot for g2408.

    Source: docs/research/g2408-protocol.md + the legacy P1.4 capability
    snapshot at docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md.
    """
    c = CAPABILITIES
    # Confirmed True on g2408
    assert c.lidar_navigation is True

    # Confirmed False on g2408 (snapshot)
    assert c.ai_detection is False
    assert c.multi_floor_map is False
    assert c.customized_cleaning is False
    assert c.shortcuts is False
    assert c.voice_assistant is False
    assert c.dnd_task is False
    assert c.cleaning_route is False
    assert c.camera_streaming is False


def test_capabilities_singleton():
    """Capabilities() always returns the same instance — frozen, no per-config differences."""
    from custom_components.dreame_a2_mower.mower.capabilities import CAPABILITIES as c1
    from custom_components.dreame_a2_mower.mower.capabilities import CAPABILITIES as c2
    assert c1 is c2
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/mower/test_capabilities.py -v
```

Expected: ImportError on `Capabilities` / `CAPABILITIES`.

- [ ] **Step 3: Implement capabilities.py**

Create `custom_components/dreame_a2_mower/mower/capabilities.py`:

```python
"""g2408 capability flags — frozen constants.

The Dreame A2 mower (g2408) is a single-model integration. Capability
flags are not runtime-resolved against a per-model registry (that
machinery was deleted in legacy P1.4 — the upstream blob had no g2408
entry, so the lookup was provably inert).

The values here come from the offline snapshot derived from 3 weeks of
MQTT probe logs + decompression of the legacy DREAME_MODEL_CAPABILITIES
blob. See ``docs/research/g2408-protocol.md`` §2.1 for the property
mapping that drives each flag.

If a future firmware introduces a property never observed in the
snapshot scan (e.g., the integration sees ``s4.22 AI_DETECTION`` push
for the first time), the flag is added here AND covered by a regression
test.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capabilities:
    """g2408 capability snapshot — every flag is a constant."""

    # Confirmed True on g2408 — MAP_SAVING (s13.1) never observed.
    lidar_navigation: bool = True

    # All confirmed False per the snapshot — these properties never
    # arrive on MQTT in 3 weeks of probe logs.
    ai_detection: bool = False
    auto_charging: bool = False
    auto_rename_segment: bool = False
    auto_switch_settings: bool = False
    backup_map: bool = False
    camera_streaming: bool = False
    cleangenius: bool = False
    cleangenius_auto: bool = False
    cleaning_route: bool = False
    customized_cleaning: bool = False
    dnd: bool = False
    dnd_task: bool = False
    extended_furnitures: bool = False
    fill_light: bool = False
    floor_direction_cleaning: bool = False
    floor_material: bool = False
    fluid_detection: bool = False
    gen5: bool = False
    large_particles_boost: bool = False
    lensbrush: bool = False
    map_object_offset: bool = False
    max_suction_power: bool = False
    multi_floor_map: bool = False
    new_furnitures: bool = False
    new_state: bool = False
    obstacle_image_crop: bool = False
    obstacles: bool = False
    off_peak_charging: bool = False
    pet_detective: bool = False
    pet_furniture: bool = False
    pet_furnitures: bool = False
    saved_furnitures: bool = False
    segment_slow_clean_route: bool = False
    segment_visibility: bool = False
    shortcuts: bool = False
    task_type: bool = False
    voice_assistant: bool = False
    wifi_map: bool = False


CAPABILITIES: Capabilities = Capabilities()
"""The single global Capabilities instance for g2408. Import this rather
than instantiating Capabilities() directly."""
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/mower/test_capabilities.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/capabilities.py tests/mower/test_capabilities.py
git commit -m "$(cat <<'EOF'
F1.2.2: Capabilities frozen constants (g2408 snapshot)

Lifts the P1.4 capability snapshot into a frozen dataclass with
no runtime resolution. The DREAME_MODEL_CAPABILITIES blob lookup
was provably inert on g2408 (legacy P1.4.4 deleted it); these
constants are the integration's authoritative capability state.

Single CAPABILITIES instance is the import target. Frozen so
nothing accidentally mutates flags at runtime.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.2.3: Property mapping table — F1-minimal entries + disambiguator slot

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/property_mapping.py`
- Create: `tests/mower/test_property_mapping.py`

F1 needs (siid, piid) entries for the three fields used: `state` (s2.1), `battery_level` (s3.1), `charging_status` (s3.2). The disambiguator pattern from spec §3 is wired in from day 1, even though no F1 entry needs one — establishing the shape now is cheaper than retrofitting.

- [ ] **Step 1: Write the failing test**

Create `tests/mower/test_property_mapping.py`:

```python
"""Property mapping — the (siid, piid) → field_name table."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.property_mapping import (
    PROPERTY_MAPPING,
    PropertyMappingEntry,
    resolve_field,
)


def test_state_maps_to_s2p1():
    """The 'state' field maps to (siid=2, piid=1) per protocol-doc §2.1."""
    entry = PROPERTY_MAPPING[(2, 1)]
    assert entry.field_name == "state"
    assert entry.disambiguator is None


def test_battery_level_maps_to_s3p1():
    entry = PROPERTY_MAPPING[(3, 1)]
    assert entry.field_name == "battery_level"


def test_charging_status_maps_to_s3p2():
    entry = PROPERTY_MAPPING[(3, 2)]
    assert entry.field_name == "charging_status"


def test_resolve_field_with_no_disambiguator():
    """Common case: resolve_field returns the primary field_name."""
    assert resolve_field((2, 1), value=1) == "state"
    assert resolve_field((3, 1), value=72) == "battery_level"


def test_resolve_field_unknown_pair_returns_none():
    """Unknown (siid, piid) returns None (caller emits NOVEL warning)."""
    assert resolve_field((9, 99), value=42) is None


def test_disambiguator_pattern_is_supported():
    """The disambiguator slot exists on PropertyMappingEntry and is
    invoked by resolve_field when present.

    Spec §3 documents the pattern for multi-purpose (siid, piid) pairs
    such as the robot-voice / notification-type slot that hasn't been
    catalogued in F1's minimal mapping. We verify the wiring exists by
    constructing a synthetic entry."""
    def _disambiguate(value: object) -> str:
        return "alt_field" if isinstance(value, dict) else "primary_field"

    entry = PropertyMappingEntry(
        field_name="primary_field",
        disambiguator=_disambiguate,
    )
    assert entry.field_name == "primary_field"
    assert entry.disambiguator is not None
    # Direct call test
    assert _disambiguate(42) == "primary_field"
    assert _disambiguate({"x": 1}) == "alt_field"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/mower/test_property_mapping.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement property_mapping.py**

Create `custom_components/dreame_a2_mower/mower/property_mapping.py`:

```python
"""(siid, piid) → field_name mapping table for g2408.

Per spec §3 cross-cutting commitment: this is the single source of
truth for property mapping. No overlay/merge gymnastics.

The mapping supports **named disambiguators** for multi-purpose
(siid, piid) pairs. At least one such pair is documented on g2408
(the robot-voice / notification-type slot — exact siid/piid TBD as
the rebuild progresses). When an entry has a disambiguator callable,
it is invoked with the inbound payload value and returns the
alternate field name when the primary mapping isn't right.

Subsequent phases (F2..F7) extend this table as MowerState gains
fields. Each new entry MUST cite its protocol-doc §2.1 source.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PropertyMappingEntry:
    """One row of the property mapping table.

    field_name: the primary MowerState field this (siid, piid) feeds.
    disambiguator: optional callable that inspects the payload value
                   and returns an alternate field name when the primary
                   doesn't apply. Returns the primary field_name when
                   the primary applies. Returns None to indicate
                   "drop this push".
    """

    field_name: str
    disambiguator: Callable[[Any], str | None] | None = None


# F1-minimal table. F2..F7 add entries.
# Each entry's primary citation is in docs/research/g2408-protocol.md §2.1.
PROPERTY_MAPPING: dict[tuple[int, int], PropertyMappingEntry] = {
    (2, 1): PropertyMappingEntry(field_name="state"),                 # s2.1 STATUS
    (3, 1): PropertyMappingEntry(field_name="battery_level"),         # s3.1 BATTERY_LEVEL
    (3, 2): PropertyMappingEntry(field_name="charging_status"),       # s3.2 CHARGING_STATUS
}


def resolve_field(siid_piid: tuple[int, int], value: Any) -> str | None:
    """Resolve a (siid, piid) push to its target MowerState field name.

    Returns None if the pair is unknown — the caller is responsible
    for emitting a [NOVEL/property] warning in that case.

    If the entry has a disambiguator, it is invoked with the value and
    its return decides the field. Otherwise the primary field_name is
    returned unconditionally.
    """
    entry = PROPERTY_MAPPING.get(siid_piid)
    if entry is None:
        return None
    if entry.disambiguator is None:
        return entry.field_name
    return entry.disambiguator(value)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/mower/test_property_mapping.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/property_mapping.py tests/mower/test_property_mapping.py
git commit -m "$(cat <<'EOF'
F1.2.3: property mapping table with disambiguator support

The (siid, piid) → field_name table for g2408. F1 only needs three
entries (state, battery_level, charging_status); the table grows
with each subsequent phase.

The disambiguator pattern from spec §3 is wired in from day 1 even
though no F1 entry needs one. At least one g2408 (siid, piid) pair
is multi-purpose (robot-voice / notification-type slot per user
note); having the resolution mechanism in place avoids retrofitting
when that pair gets characterised.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.2.4: Error codes map (apk fault index)

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/error_codes.py`
- Create: `tests/mower/test_error_codes.py`

F1 needs the error_codes table even though no F1 entity directly reads it — `MowerState` doesn't have an `error_code` field yet (F2 adds it). The table is included in F1 so it's available the moment F2 starts. Source: docs/research/g2408-protocol.md §2.1 row s2.2.

- [ ] **Step 1: Write the failing test**

Create `tests/mower/test_error_codes.py`:

```python
"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
    ERROR_CODE_DESCRIPTIONS,
    describe_error,
)


def test_known_error_codes_mapped():
    """The most-confirmed error codes from protocol-doc §2.1 row s2.2 are mapped."""
    assert "HANGING" in ERROR_CODE_DESCRIPTIONS[0].upper()
    assert "BATTERY" in ERROR_CODE_DESCRIPTIONS[24].upper()
    assert "HUMAN" in ERROR_CODE_DESCRIPTIONS[27].upper()
    assert "WEATHER" in ERROR_CODE_DESCRIPTIONS[56].upper() or "RAIN" in ERROR_CODE_DESCRIPTIONS[56].upper()
    assert "COVER" in ERROR_CODE_DESCRIPTIONS[73].upper()


def test_describe_known_returns_description():
    assert describe_error(24) == ERROR_CODE_DESCRIPTIONS[24]


def test_describe_unknown_returns_fallback():
    """Unknown codes return a fallback description. The caller (or a
    higher layer) emits a NOVEL warning for unknown codes; this function
    just returns a useful display string."""
    s = describe_error(9999)
    assert "9999" in s
    assert "unknown" in s.lower()
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/mower/test_error_codes.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement error_codes.py**

Create `custom_components/dreame_a2_mower/mower/error_codes.py`:

```python
"""Mower error code → human description map.

Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.2``.

The s2.2 push on g2408 carries an error code per the apk fault index
(originally reverse-engineered from the Dreame Smart Life app's
decompiled APK; cross-validated against live captures during P1+P2).

Some s2.2 values that arrive on g2408 are actually phase / mode codes
that the apk does not classify as faults (e.g., 56 = rain protection,
71 = positioning failed). These are routed to dedicated binary_sensor
entities in F2; the error-code description map here only covers
genuine faults.

Codes documented but not in this map yield a fallback "Unknown error N"
description. The coordinator emits a [NOVEL/error_code] warning when
it sees a code not in this table.
"""
from __future__ import annotations


# Confirmed entries from docs/research/g2408-protocol.md §2.1.
# Add codes here when an apk-confirmed fault description becomes
# available; the table stays purely g2408 (no upstream-vacuum codes).
ERROR_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Hanging — mower is stuck or hanging",
    24: "Battery low",
    27: "Human detected",
    56: "Bad weather (rain protection active)",
    71: "Positioning failed (SLAM relocation needed)",
    73: "Top cover open",
}


def describe_error(code: int) -> str:
    """Return a human-readable description for the given error code.

    Returns a fallback string for unknown codes — the caller is
    responsible for emitting a [NOVEL/error_code] warning.
    """
    if code in ERROR_CODE_DESCRIPTIONS:
        return ERROR_CODE_DESCRIPTIONS[code]
    return f"Unknown error {code}"
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/mower/test_error_codes.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py tests/mower/test_error_codes.py
git commit -m "$(cat <<'EOF'
F1.2.4: error code descriptions (apk fault index, g2408 only)

Six confirmed entries covering the most-cited fault codes from
protocol-doc §2.1 row s2.2. Pure g2408 — no upstream-vacuum holdover
codes. Unknown codes return a fallback "Unknown error N" description;
the coordinator emits NOVEL warnings for unmapped codes.

This table is added in F1 so F2 can wire the error_code MowerState
field to it without an extra phase.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.2.5: Run the full mower/ test suite + smoke import

- [ ] **Step 1: Run full mower/ tests**

```bash
pytest tests/mower/ -v
```

Expected: all green (4 + 3 + 6 + 3 = 16 tests).

- [ ] **Step 2: Smoke-test the package imports**

```bash
python3 -c "
from custom_components.dreame_a2_mower.mower.state import MowerState, State, ChargingStatus
from custom_components.dreame_a2_mower.mower.capabilities import CAPABILITIES, Capabilities
from custom_components.dreame_a2_mower.mower.property_mapping import PROPERTY_MAPPING, resolve_field
from custom_components.dreame_a2_mower.mower.error_codes import ERROR_CODE_DESCRIPTIONS, describe_error

s = MowerState(state=State.WORKING, battery_level=72, charging_status=ChargingStatus.NOT_CHARGING)
assert resolve_field((2, 1), s.state) == 'state'
assert CAPABILITIES.lidar_navigation
assert describe_error(24) == ERROR_CODE_DESCRIPTIONS[24]
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Smoke-test no HA imports leaked**

```bash
grep -rn "import homeassistant\|from homeassistant" custom_components/dreame_a2_mower/mower/
```

Expected: zero matches. The domain layer is HA-independent per spec §3 layer 2.

---

## Phase F1.3 — HA integration scaffold

### Task F1.3.1: __init__.py + manifest.json + const.py

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py` (was empty)
- Create: `custom_components/dreame_a2_mower/manifest.json`
- Create: `custom_components/dreame_a2_mower/const.py`

The skeleton that lets HA discover and load the integration.

- [ ] **Step 1: Write manifest.json**

Create `custom_components/dreame_a2_mower/manifest.json`:

```json
{
  "domain": "dreame_a2_mower",
  "name": "Dreame A2 Mower",
  "codeowners": ["@okolbu"],
  "config_flow": true,
  "documentation": "https://github.com/okolbu/ha-dreame-a2-mower-v2",
  "integration_type": "device",
  "iot_class": "cloud_push",
  "issue_tracker": "https://github.com/okolbu/ha-dreame-a2-mower-v2/issues",
  "requirements": [
    "paho-mqtt>=2.0",
    "requests>=2.31",
    "pillow>=10.0",
    "numpy>=1.26",
    "pycryptodome>=3.20"
  ],
  "version": "0.1.0a0"
}
```

Note: `integration_type` is `device` (single-mower, single-instance) rather than `hub` (multi-device aggregator).

- [ ] **Step 2: Write const.py**

Create `custom_components/dreame_a2_mower/const.py`:

```python
"""Domain-level constants for the Dreame A2 Mower integration."""
from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "dreame_a2_mower"
"""HA domain identifier — kept identical to legacy for config-flow continuity."""

PLATFORMS: Final = ["lawn_mower", "sensor"]
"""HA platforms this integration sets up. F1 = lawn_mower + sensor only.
F2 onward extends this list."""

LOGGER: Final = logging.getLogger(__package__)
"""Module-level logger. Per spec §3, every layer-3 file uses this."""

# Config flow keys
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_COUNTRY: Final = "country"

# Default values
DEFAULT_NAME: Final = "Dreame A2 Mower"
DEFAULT_COUNTRY: Final = "eu"

# Log prefixes — single source per spec §3 cross-cutting commitment.
LOG_NOVEL_PROPERTY: Final = "[NOVEL/property]"
LOG_NOVEL_VALUE: Final = "[NOVEL/value]"
LOG_NOVEL_KEY: Final = "[NOVEL_KEY]"
LOG_EVENT: Final = "[EVENT]"
LOG_SESSION: Final = "[SESSION]"
LOG_MAP: Final = "[MAP]"
```

- [ ] **Step 3: Write __init__.py**

Replace the empty `custom_components/dreame_a2_mower/__init__.py` with:

```python
"""The Dreame A2 Mower integration.

Per spec §3 layer 3 — this is the HA glue layer. Wires the typed
domain model (mower/) to Home Assistant's coordinator + entity
infrastructure.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Dreame A2 Mower integration from a config entry."""
    LOGGER.info("Setting up %s integration", DOMAIN)

    # F1: coordinator setup is added in F1.4. Stub for now so the
    # integration can register without errors.
    from .coordinator import DreameA2MowerCoordinator

    coordinator = DreameA2MowerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    LOGGER.info("Unloading %s integration", DOMAIN)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
```

- [ ] **Step 4: Smoke check**

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
# Just verify the syntax is valid; HA imports are missing in the venv
# but py_compile catches structural errors.
import py_compile
for f in [
    'custom_components/dreame_a2_mower/__init__.py',
    'custom_components/dreame_a2_mower/const.py',
]:
    py_compile.compile(f, doraise=True)
print('ok')
"
```

Expected: `ok`. ImportErrors on `homeassistant.*` are normal — those are runtime imports, not compile-time.

Validate the manifest JSON:

```bash
python3 -c "import json; print(json.load(open('custom_components/dreame_a2_mower/manifest.json'))['domain'])"
```

Expected: `dreame_a2_mower`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py \
        custom_components/dreame_a2_mower/manifest.json \
        custom_components/dreame_a2_mower/const.py
git commit -m "$(cat <<'EOF'
F1.3.1: HA integration scaffold — __init__, manifest, const

Establishes the HA discoverability shell. async_setup_entry forwards
to the lawn_mower + sensor platforms (F1 scope) and instantiates the
coordinator (built in F1.4). const.py defines the domain identifier,
platforms list, logger, config-flow keys, and the log-prefix constants
per spec §3.

manifest.json declares integration_type=device (single-mower) and
the minimum runtime requirements: paho-mqtt, requests, pillow,
numpy, pycryptodome. Version starts at 0.1.0a0 per spec §2 HACS
pre-release flag.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.3.2: config_flow.py minimal — username/password/country

**Files:**
- Create: `custom_components/dreame_a2_mower/config_flow.py`
- Create: `custom_components/dreame_a2_mower/strings.json` (F1.6 fills it; this task creates a minimal stub for the config_flow translations)
- Create: `custom_components/dreame_a2_mower/translations/en.json` (minimal)

- [ ] **Step 1: Write config_flow.py**

Create `custom_components/dreame_a2_mower/config_flow.py`:

```python
"""Config flow for the Dreame A2 Mower integration.

F1: minimal user-step flow. Just collects cloud credentials + country.
F4 (settings) extends this with options-flow for archive retention and
station bearing.

Per spec §5.9 credential discipline: credentials are stored in HA's
encrypted-at-rest config-entry secrets via the standard
``CONF_USERNAME`` / ``CONF_PASSWORD`` constants.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_COUNTRY,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
)


class DreameA2MowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup conversation."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: collect cloud credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # F1: no live validation yet — that's added in F1.4 once the
            # cloud client exists. For now, just accept what's entered.
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): vol.In(
                        ["eu", "us", "cn", "ru", "i2", "sg", "de"]
                    ),
                }
            ),
            errors=errors,
        )
```

- [ ] **Step 2: Write minimal strings.json**

Create `custom_components/dreame_a2_mower/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Dreame A2 Mower",
        "description": "Enter your Dreame cloud credentials.",
        "data": {
          "username": "Email or phone",
          "password": "Password",
          "country": "Cloud region"
        }
      }
    },
    "abort": {
      "already_configured": "Mower is already configured."
    }
  }
}
```

- [ ] **Step 3: Write minimal en.json translation**

```bash
mkdir -p custom_components/dreame_a2_mower/translations
```

Create `custom_components/dreame_a2_mower/translations/en.json` with the same content as `strings.json` (HA convention: `strings.json` is the source-of-truth, `translations/en.json` is the rendered English version; they're identical for `en`).

- [ ] **Step 4: Smoke check**

```bash
python3 -c "
import json, py_compile
py_compile.compile('custom_components/dreame_a2_mower/config_flow.py', doraise=True)
json.load(open('custom_components/dreame_a2_mower/strings.json'))
json.load(open('custom_components/dreame_a2_mower/translations/en.json'))
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/config_flow.py \
        custom_components/dreame_a2_mower/strings.json \
        custom_components/dreame_a2_mower/translations/
git commit -m "$(cat <<'EOF'
F1.3.2: config_flow minimal — username/password/country

Single-step user flow accepting cloud credentials. F1 has no live
validation; F1.4 wires the cloud client and adds an authentication
check. Country defaults to "eu" matching the legacy default.

strings.json + translations/en.json contain only the F1 user-step
strings. F2..F7 extend both as more options are added.

Per spec §5.9: credentials stored via the standard CONF_USERNAME /
CONF_PASSWORD config-entry secrets mechanism — never written to
disk by the integration outside that path.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Phase F1.4 — Coordinator + MQTT/cloud clients

### Task F1.4.1: Lift cloud + MQTT client modules from legacy

**Files:**
- Copy: legacy `custom_components/dreame_a2_mower/dreame/protocol.py` → `custom_components/dreame_a2_mower/cloud_client.py`
- Copy relevant MQTT bits from legacy `dreame/device.py` → `custom_components/dreame_a2_mower/mqtt_client.py`

The cloud client lifts cleanly from legacy `dreame/protocol.py` (it's the auth + device-info + OSS-key fetching code). The MQTT client needs more curation: extract just the connection/subscribe/dispatch logic from `dreame/device.py` without the property-store machinery.

**This task may run long.** If during the lift the implementer finds the legacy code too tangled, STOP and report DONE_WITH_CONCERNS — the controller will pause and ask the user whether to continue lifting or rewrite from scratch.

- [ ] **Step 1: Identify cloud_client targets**

Read legacy `custom_components/dreame_a2_mower/dreame/protocol.py`. The class `DreameMowerProtocol` contains the cloud-RPC + auth + OSS download paths. Identify:
- Auth flow (login, token refresh)
- `get_devices` / device-info fetching
- `get_interim_file_url` (OSS download URL fetching)
- `get_file` (OSS file download)
- `get_properties` / `set_properties` / `action` (cloud-RPC; will fail with 80001 on g2408 but the structure is needed)

Report what's found before lifting.

- [ ] **Step 2: Copy cloud client**

```bash
cp /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/protocol.py \
   custom_components/dreame_a2_mower/cloud_client.py
```

Then edit the new `cloud_client.py`:
- Remove any HA imports that aren't needed (the cloud client should import from `homeassistant.exceptions` for raising `ConfigEntryAuthFailed` etc., but nothing platform-specific)
- Rename the class from `DreameMowerProtocol` to `DreameA2CloudClient` for clarity
- Remove the MQTT client embedding if any (MQTT goes in its own module)
- Add docstrings citing `docs/research/g2408-protocol.md` §1 for the transport details

- [ ] **Step 3: Copy MQTT client logic**

Read legacy `dreame/device.py` lines around the `_message_callback` / connect / subscribe / publish methods. Extract the MQTT-specific code into a new `custom_components/dreame_a2_mower/mqtt_client.py` with class `DreameA2MqttClient`.

The MQTT client interface F1 needs:
- `connect(host, port, username, password)` — establish the TLS connection
- `subscribe(topic)` — subscribe to `/status/<did>/...`
- `register_callback(callback)` — register a function called on every inbound message; the callback receives `(topic, payload_dict)`
- `disconnect()` — clean teardown

The full property-store / dispatch / decoding code stays in the coordinator (F1.4.2); the MQTT client is dumb pipe.

- [ ] **Step 4: Smoke check**

```bash
python3 -c "
import py_compile
py_compile.compile('custom_components/dreame_a2_mower/cloud_client.py', doraise=True)
py_compile.compile('custom_components/dreame_a2_mower/mqtt_client.py', doraise=True)
print('ok')
"
```

Expected: `ok`. ImportErrors on `homeassistant.*` or third-party libs (paho-mqtt, requests) are normal in the test venv.

- [ ] **Step 5: Update lessons-from-legacy.md**

Append to `docs/lessons-from-legacy.md`:

```markdown
## F1.4.1: cloud + MQTT client lift

- **Cloud RPC 80001 failure mode** — see legacy `dreame/protocol.py`
  the `_send_command` retry path. On g2408, cloud-side
  `set_properties` / `action` / `get_properties` consistently return
  HTTP code 80001 ("device unreachable") even while MQTT is actively
  pushing telemetry. The integration treats this as expected, not
  an error. Source: `docs/research/g2408-protocol.md` §1.2.
- **OSS download fallback path works** — `get_interim_file_url` +
  signed-URL fetch is the only reliable RPC path on g2408. Used for
  session-summary JSONs and LiDAR PCDs.
- **MQTT topic format** —
  `/status/<did>/<mac-hash>/dreame.mower.g2408/<region>/`. The
  region prefix is from the cloud login (`eu` / `us` / etc.).
```

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py \
        custom_components/dreame_a2_mower/mqtt_client.py \
        docs/lessons-from-legacy.md
git commit -m "$(cat <<'EOF'
F1.4.1: lift cloud + MQTT client from legacy

cloud_client.py = legacy dreame/protocol.py with the class renamed
to DreameA2CloudClient. Auth, device-info, OSS download paths are
the only reliable cloud surfaces on g2408 (cloud RPC returns 80001).

mqtt_client.py = the MQTT connection/subscribe/dispatch surface
extracted from legacy dreame/device.py. Dumb-pipe interface; the
coordinator owns property decoding and state updates.

lessons-from-legacy.md: first three entries documenting the cloud
RPC 80001 expectation, the OSS-download fallback path, and the MQTT
topic format.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.4.2: Coordinator skeleton with state-update flow

**Files:**
- Create: `custom_components/dreame_a2_mower/coordinator.py`
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/integration/test_coordinator.py`

The coordinator owns: the `MowerState`, the cloud client, the MQTT client. On inbound MQTT messages, it routes through `protocol/` decoders and `mower/property_mapping.resolve_field()` to update `MowerState`, then calls `async_set_updated_data`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_coordinator.py`:

```python
"""Coordinator tests — state update flow.

These use pytest-homeassistant-custom-component (added in F1.4.3).
F1.4.2 starts with a non-HA test that just verifies the
update-state-from-payload logic.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)
from custom_components.dreame_a2_mower.coordinator import (
    apply_property_to_state,
)


def test_apply_battery_level_property():
    """A (3, 1) property push updates MowerState.battery_level."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=1, value=72)
    assert new_state.battery_level == 72
    # Other fields unchanged
    assert new_state.state is None
    assert new_state.charging_status is None


def test_apply_state_property():
    """A (2, 1) property push updates MowerState.state."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=2, piid=1, value=1)
    assert new_state.state == State.WORKING


def test_apply_charging_status_property():
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=2, value=1)
    assert new_state.charging_status == ChargingStatus.CHARGING


def test_apply_unknown_property_returns_unchanged_state():
    """Unknown (siid, piid) is logged elsewhere; the state is unchanged."""
    state = MowerState(battery_level=50)
    new_state = apply_property_to_state(state, siid=99, piid=99, value="weird")
    assert new_state == state


def test_apply_property_with_invalid_state_value_keeps_field_none():
    """Invalid enum values are dropped (the integration logs NOVEL elsewhere)."""
    state = MowerState()
    # 999 is not a valid State enum
    new_state = apply_property_to_state(state, siid=2, piid=1, value=999)
    assert new_state.state is None
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pytest tests/integration/test_coordinator.py -v
```

Expected: ImportError on `apply_property_to_state`.

- [ ] **Step 3: Implement coordinator.py**

Create `custom_components/dreame_a2_mower/coordinator.py`:

```python
"""Coordinator for the Dreame A2 Mower integration.

Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
MowerState, and the dispatch from inbound MQTT pushes to state
updates. Entities subscribe to coordinator updates and read from
``coordinator.data`` (the MowerState).
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    LOG_NOVEL_PROPERTY,
    LOGGER,
)
from .mower.property_mapping import resolve_field
from .mower.state import ChargingStatus, MowerState, State


def apply_property_to_state(
    state: MowerState, siid: int, piid: int, value: Any
) -> MowerState:
    """Return a new MowerState with the given property push applied.

    Returns the unchanged state if (siid, piid) is unknown OR if value
    can't be coerced to the field's expected type. Logs at WARNING in
    both cases (caller can override via the LOGGER override).

    Pure function — no side effects beyond logging. F1's three known
    fields (state, battery_level, charging_status) are handled here;
    F2..F7 extend the dispatch.
    """
    field_name = resolve_field((siid, piid), value)
    if field_name is None:
        LOGGER.warning(
            "%s siid=%d piid=%d value=%r — unmapped property",
            LOG_NOVEL_PROPERTY,
            siid,
            piid,
            value,
        )
        return state

    if field_name == "state":
        try:
            new_value: Any = State(int(value))
        except (ValueError, TypeError):
            LOGGER.warning(
                "%s s2.1 STATE: value=%r outside known State enum — dropping",
                LOG_NOVEL_PROPERTY,
                value,
            )
            return state
        return dataclasses.replace(state, state=new_value)

    if field_name == "battery_level":
        try:
            return dataclasses.replace(state, battery_level=int(value))
        except (ValueError, TypeError):
            return state

    if field_name == "charging_status":
        try:
            return dataclasses.replace(state, charging_status=ChargingStatus(int(value)))
        except (ValueError, TypeError):
            LOGGER.warning(
                "%s s3.2 CHARGING_STATUS: value=%r outside enum — dropping",
                LOG_NOVEL_PROPERTY,
                value,
            )
            return state

    # Resolved to an unknown field name — should never happen given the
    # current PROPERTY_MAPPING table, but fail safe.
    LOGGER.warning(
        "%s siid=%d piid=%d resolved to unknown field=%r",
        LOG_NOVEL_PROPERTY,
        siid,
        piid,
        field_name,
    )
    return state


class DreameA2MowerCoordinator(DataUpdateCoordinator[MowerState]):
    """Coordinates MQTT + cloud clients and the typed MowerState."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-based; we don't poll
        )
        self.entry = entry
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._country = entry.data[CONF_COUNTRY]

        # Initialize empty MowerState — fields fill in as MQTT pushes arrive
        self.data = MowerState()

    async def _async_update_data(self) -> MowerState:
        """Called once at first refresh and on explicit refresh requests.

        F1: no-op return current state. F1.4.3 wires the cloud + MQTT
        clients here.
        """
        return self.data

    def handle_property_push(self, siid: int, piid: int, value: Any) -> None:
        """Apply a property push and notify entities. Called from the
        MQTT message callback."""
        new_state = apply_property_to_state(self.data, siid, piid, value)
        if new_state != self.data:
            self.async_set_updated_data(new_state)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/integration/test_coordinator.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py \
        tests/integration/
git commit -m "$(cat <<'EOF'
F1.4.2: coordinator skeleton + state-update flow

DreameA2MowerCoordinator extends DataUpdateCoordinator[MowerState].
Push-based (update_interval=None); the MQTT message callback drives
state updates via handle_property_push.

apply_property_to_state is the pure function that takes a
(siid, piid, value) push and returns the new MowerState. It uses
property_mapping.resolve_field to find the target field and applies
type coercion. Unknown pairs and invalid values are logged at WARNING
with the [NOVEL/property] prefix.

F1's three properties (state, battery_level, charging_status) are
fully wired. F2..F7 extend the dispatch.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.4.3: Wire cloud auth + MQTT subscribe in coordinator

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

The coordinator's `_async_update_data` (called on first refresh) needs to authenticate with the cloud, fetch device info, and start the MQTT client. The MQTT client's incoming-message callback dispatches through `handle_property_push`.

- [ ] **Step 1: Update coordinator.py**

Replace `_async_update_data` and add MQTT setup:

```python
# Insert near the top of coordinator.py:
from .cloud_client import DreameA2CloudClient
from .mqtt_client import DreameA2MqttClient

# Replace the existing _async_update_data + add new helpers in the class body:

    async def _async_update_data(self) -> MowerState:
        """First-refresh path — auth, device discovery, MQTT subscribe.

        Subsequent refreshes are push-driven via the MQTT callback;
        this method only re-runs if the user manually refreshes the
        integration.
        """
        if not hasattr(self, "_cloud"):
            self._cloud = await self.hass.async_add_executor_job(
                self._init_cloud
            )
            await self.hass.async_add_executor_job(self._init_mqtt)
        return self.data

    def _init_cloud(self) -> DreameA2CloudClient:
        """Authenticate with the Dreame cloud and pick up device info."""
        client = DreameA2CloudClient(
            username=self._username,
            password=self._password,
            country=self._country,
        )
        client.login()
        device_info = client.get_devices()[0]  # single-mower
        self._device_did = device_info["did"]
        self._device_mac = device_info["mac"]
        self._device_model = device_info["model"]
        self._mqtt_host = device_info["bindDomain"].split(":")[0]
        self._mqtt_port = int(device_info["bindDomain"].split(":")[1])
        LOGGER.info(
            "Cloud auth ok; device %s model=%s host=%s",
            self._device_did,
            self._device_model,
            self._mqtt_host,
        )
        return client

    def _init_mqtt(self) -> None:
        """Open the MQTT connection and subscribe to the mower's status topic."""
        self._mqtt = DreameA2MqttClient()
        self._mqtt.register_callback(self._on_mqtt_message)
        self._mqtt.connect(
            host=self._mqtt_host,
            port=self._mqtt_port,
            username=self._username,
            password=self._cloud.get_mqtt_password(),  # short-lived OTC password
        )
        topic = f"/status/{self._device_did}/+/{self._device_model}/{self._country}/"
        self._mqtt.subscribe(topic)
        LOGGER.info("Subscribed to %s", topic)

    def _on_mqtt_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Dispatcher for inbound MQTT messages.

        Each message is a properties_changed batch with {"params": [
            {"siid": ..., "piid": ..., "value": ...},
            ...
        ]}.
        """
        method = payload.get("method")
        if method != "properties_changed":
            # F1: only properties_changed. F5 adds event_occured handling.
            return
        params = payload.get("params") or []
        for p in params:
            if "siid" in p and "piid" in p:
                self.handle_property_push(
                    siid=int(p["siid"]),
                    piid=int(p["piid"]),
                    value=p.get("value"),
                )
```

- [ ] **Step 2: Re-run integration tests**

```bash
pytest tests/integration/test_coordinator.py -v
```

Expected: 5 still passing (the apply_property_to_state tests don't depend on the new methods).

- [ ] **Step 3: Smoke check syntax**

```bash
python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "$(cat <<'EOF'
F1.4.3: wire cloud auth + MQTT subscribe in coordinator

The coordinator's _async_update_data now performs first-refresh setup:
authenticate with the Dreame cloud, fetch device info (did, mac,
model, bindDomain), then open the MQTT connection and subscribe to
the mower's status topic.

Inbound MQTT messages with method=properties_changed are dispatched
through handle_property_push for each (siid, piid, value) tuple in
params. Other methods (event_occured etc.) are ignored in F1; F5
adds session-summary event handling.

All blocking I/O (cloud login, MQTT connect) goes through
hass.async_add_executor_job per spec §3 async-first commitment.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Phase F1.5 — Entities

### Task F1.5.1: lawn_mower platform entity

**Files:**
- Create: `custom_components/dreame_a2_mower/lawn_mower.py`

The HA `lawn_mower` platform handles state-aware start/pause/dock through the platform's standard contract. F1's lawn_mower entity reads `coordinator.data.state` and maps it to `LawnMowerActivity`. Action calls (`start_mowing`, `pause`, `dock`) are stubs that LOG and no-op — F3 wires them to actual cloud actions.

- [ ] **Step 1: Write lawn_mower.py**

Create `custom_components/dreame_a2_mower/lawn_mower.py`:

```python
"""LawnMower platform for the Dreame A2 Mower integration.

Per spec §5.1: the primary state + control surface. F1 reads state
from MowerState; F3 wires action calls to cloud RPC.
"""
from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import State


# Map MowerState.State → LawnMowerActivity. None entries map to ERROR
# in HA terms (HA's LawnMowerActivity has no IDLE state distinct from
# DOCKED, so we synthesize).
_STATE_TO_ACTIVITY: dict[State, LawnMowerActivity] = {
    State.WORKING: LawnMowerActivity.MOWING,
    State.STANDBY: LawnMowerActivity.DOCKED,
    State.PAUSED: LawnMowerActivity.PAUSED,
    State.RETURNING: LawnMowerActivity.RETURNING,
    State.CHARGING: LawnMowerActivity.DOCKED,
    State.MAPPING: LawnMowerActivity.MOWING,
    State.CHARGED: LawnMowerActivity.DOCKED,
    State.UPDATING: LawnMowerActivity.DOCKED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lawn_mower platform from a config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2LawnMower(coordinator)])


class DreameA2LawnMower(
    CoordinatorEntity[DreameA2MowerCoordinator], LawnMowerEntity
):
    """The Dreame A2 mower as an HA lawn_mower entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lawn_mower"

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Map MowerState.state to LawnMowerActivity."""
        s = self.coordinator.data.state
        if s is None:
            return None
        return _STATE_TO_ACTIVITY.get(s)

    async def async_start_mowing(self) -> None:
        """F1: log and no-op. F3 wires this to cloud RPC."""
        LOGGER.info("start_mowing requested — F1 stub (F3 will wire to cloud)")

    async def async_pause(self) -> None:
        LOGGER.info("pause requested — F1 stub")

    async def async_dock(self) -> None:
        LOGGER.info("dock requested — F1 stub")
```

- [ ] **Step 2: Smoke check**

```bash
python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/lawn_mower.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/lawn_mower.py
git commit -m "$(cat <<'EOF'
F1.5.1: lawn_mower platform entity

DreameA2LawnMower wraps the coordinator's MowerState.state into HA's
LawnMowerActivity enum. State mapping covers every g2408 State enum
value (WORKING/STANDBY/PAUSED/RETURNING/CHARGING/MAPPING/CHARGED/
UPDATING). MAPPING maps to MOWING (the BUILDING-mode session is
also mowing in HA terms).

F1 supports the START_MOWING / PAUSE / DOCK feature flags; the
action handlers log a stub message and no-op. F3 wires them to the
cloud RPC layer.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.5.2: sensor.py — battery_level + charging_status

**Files:**
- Create: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 1: Write sensor.py**

Create `custom_components/dreame_a2_mower/sensor.py`:

```python
"""Sensor platform for the Dreame A2 Mower.

F1: battery_level + charging_status. F2 adds the rest of §2.1's
confirmed-source sensors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ChargingStatus, MowerState


@dataclass(frozen=True, kw_only=True)
class DreameA2SensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], Any]


SENSORS: tuple[DreameA2SensorEntityDescription, ...] = (
    DreameA2SensorEntityDescription(
        key="battery_level",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.battery_level,
    ),
    DreameA2SensorEntityDescription(
        key="charging_status",
        name="Charging status",
        device_class=SensorDeviceClass.ENUM,
        options=[c.name.lower() for c in ChargingStatus],
        value_fn=lambda s: (s.charging_status.name.lower() if s.charging_status is not None else None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DreameA2Sensor(coordinator, desc) for desc in SENSORS]
    )


class DreameA2Sensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed sensor entity."""

    _attr_has_entity_name = True
    entity_description: DreameA2SensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)
```

- [ ] **Step 2: Smoke check**

```bash
python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/sensor.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "$(cat <<'EOF'
F1.5.2: sensor.py with battery_level + charging_status

Two F1 sensors using the frozen DreameA2SensorEntityDescription
pattern (per spec §3 layer 3 commitment to value_fn-based descriptors).

battery_level: BATTERY device class, MEASUREMENT state class, %.
charging_status: ENUM device class, options from ChargingStatus.

F2 extends SENSORS with the rest of §2.1's confirmed-source sensors
(area_mowed, position_x/y/n/e, etc.).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Phase F1.6 — Polish

### Task F1.6.1: HACS metadata + final README

**Files:**
- Create: `hacs.json`
- Create: `CONTRIBUTING.md`
- Modify: `README.md`

- [ ] **Step 1: Write hacs.json**

Create `hacs.json`:

```json
{
  "name": "Dreame A2 Mower",
  "render_readme": true,
  "homeassistant": "2025.4.0",
  "country": ["NO", "GB", "US", "FR", "DE", "ES", "IT", "NL", "SE", "PL"]
}
```

- [ ] **Step 2: Write CONTRIBUTING.md**

Create `CONTRIBUTING.md`:

```markdown
# Contributing to the Dreame A2 Mower integration

This integration is in active rebuild — see the spec at
`docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`
for the architecture and roadmap.

## Do not commit secrets

`*credentials*`, `*.env`, `*.pem`, `*.key`, `secrets.yaml`, and the
`<config>/dreame_a2_mower/` archive directory are excluded by
`.gitignore`. **Never commit cloud credentials to this repo.** If
you're sharing a debug log or probe capture, redact `username`,
`password`, `token`, `did`, and `mac` first.

The integration's `download_diagnostics` endpoint redacts those
fields automatically when producing diagnostic dumps for support
issues.

## Reporting issues

Use the GitHub issue tracker. For protocol-related bug reports,
please attach:

- The output of `download_diagnostics` (creds redacted automatically).
- Recent HA logs (search for `[NOVEL/...]` or `[EVENT]` prefixes).
- The mower's firmware version (visible in HA's Device page).

## Reverse-engineering contributions

If you're adding decoding support for a newly-observed property,
firmware variant, or message shape:

1. Add an entry to `docs/research/g2408-protocol.md` §2.1 with
   evidence (probe-log line, observed value, timing context).
2. Add a decoder to `protocol/` if the property is a structured
   blob.
3. Add a `MowerState` field with proper §2.1 citation in
   `mower/state.py`.
4. Add an entity descriptor to the appropriate platform.
5. Cite the protocol-doc row in the commit message.
```

- [ ] **Step 3: Update README**

Replace the F1.0.2 README stub with the final version:

```markdown
# Dreame A2 Mower — Home Assistant Integration

A Home Assistant integration for the **Dreame A2** robotic lawn mower
(model `dreame.mower.g2408`). Written from scratch for the A2; **not a
fork** of any upstream project.

## Status

🚧 Pre-alpha rebuild — F1 (Foundation) phase. The integration installs
and exposes the mower's state, battery, and charging status. Action
calls (start/pause/dock) are not yet wired. Full feature parity with
the legacy [`ha-dreame-a2-mower`](https://github.com/okolbu/ha-dreame-a2-mower)
repo is the F7 cutover gate.

## Roadmap

See `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`
for the full spec including the 48-item behavioral parity checklist
that gates cutover.

| Phase | Scope | Status |
|---|---|---|
| F1 | Foundation (this phase) | 🚧 In progress |
| F2 | Core state | ⏳ Pending |
| F3 | Action surface | ⏳ Pending |
| F4 | Settings (mowing + more) | ⏳ Pending |
| F5 | Session lifecycle | ⏳ Pending |
| F6 | Archives + observability | ⏳ Pending |
| F7 | LiDAR + dashboard polish + cutover | ⏳ Pending |

## Architecture

Three-layer stack:

- **`protocol/`** — pure-Python wire codecs (no `homeassistant.*`
  imports). Lifted from legacy verbatim. Tests run in a vanilla
  pytest venv.
- **`custom_components/dreame_a2_mower/mower/`** — typed domain
  layer. `MowerState` dataclass; capability constants; (siid, piid)
  → field mapping. Also no `homeassistant.*` imports.
- **`custom_components/dreame_a2_mower/`** (top level) — HA glue:
  config_flow, coordinator, entity platforms.

## Installation

**Not yet ready for general use.** Install the legacy repo while the
rebuild progresses.

Once F7 lands, install via HACS:

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add this repo's URL with category **Integration**.
3. Restart HA, then add the integration via Settings → Devices &
   Services → Add Integration → "Dreame A2 Mower".

## License

MIT — see `LICENSE`.
```

- [ ] **Step 4: Commit**

```bash
git add hacs.json CONTRIBUTING.md README.md
git commit -m "$(cat <<'EOF'
F1.6.1: HACS metadata + CONTRIBUTING + final README

hacs.json declares the integration as render_readme=true with HA
version floor 2025.4.0. Country list mirrors the legacy repo's HACS
config.

CONTRIBUTING.md documents the 'no secrets in commits' policy with
the .gitignore patterns and download_diagnostics redaction guarantee.
Also lays out the protocol-RE contribution flow: §2.1 row → protocol/
decoder → MowerState field → entity descriptor.

README replaces the F1.0.2 stub with the full integration overview,
roadmap, and install instructions (clearly marked pre-alpha).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task F1.6.2: Tag F1 release

- [ ] **Step 1: Run final test sweep**

```bash
pytest -v
```

Expected: every test passes (F1.1 protocol tests + F1.2 mower tests + F1.4 coordinator tests; ~30+ tests total).

- [ ] **Step 2: Tag and push**

```bash
git tag -a v0.1.0a0 -m "F1 — Foundation phase complete. Integration installs, displays state/battery/charging. Action calls are stubs (F3 wires them)."
git push origin v0.1.0a0
```

- [ ] **Step 3: Verify tag is on remote**

```bash
git ls-remote --tags origin
```

Expected: `v0.1.0a0` listed.

---

## Self-review checklist

Run before declaring F1 complete:

- [ ] All `pytest` tests pass (protocol/, mower/, integration/).
- [ ] No `homeassistant.*` imports in `protocol/` or `custom_components/dreame_a2_mower/mower/`.
- [ ] `manifest.json` parses cleanly; domain is `dreame_a2_mower`.
- [ ] HA reloads the integration successfully against a live g2408 (manual test).
- [ ] Cloud auth succeeds; first MQTT push updates `MowerState.state` / `battery_level` / `charging_status`.
- [ ] `lawn_mower` entity appears in HA, shows correct activity for current state.
- [ ] `sensor.battery_level` and `sensor.charging_status` show fresh values.
- [ ] `start_mowing` / `pause` / `dock` actions log the F1 stub messages (no errors).
- [ ] `download_diagnostics` is not yet wired — F6 task. Don't try to access it.
- [ ] `v0.1.0a0` tag pushed to `origin`.

## What this plan does NOT do

Out-of-scope for F1, deferred to F2..F7:

- All F2 sensors beyond battery + charging_status (area_mowed, position_*, error decode, GPS, etc.).
- F3 action surface (services, action_mode select, real cloud-RPC calls).
- F4 settings entities (s2.51 sub-fields, CFG-derived numbers/selects).
- F5 session lifecycle (live_map, archives, finalize gate, in-progress restore).
- F6 observability (novel-token registry, schema validators, diagnostic sensor, download_diagnostics).
- F7 LiDAR + dashboard polish + cutover.

## Followup tasks

After F1 lands and the user has installed and verified it works:

- [ ] Mark task #16 (Final cumulative review of F1) by dispatching the code-reviewer subagent on `v0.1.0a0`.
- [ ] Update `MEMORY.md` with the new repo path and F1-completed status.
- [ ] Begin writing the F2 plan against the actual file structure that landed.
