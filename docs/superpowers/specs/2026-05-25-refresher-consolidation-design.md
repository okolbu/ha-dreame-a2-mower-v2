# Refresher Consolidation (Design)

**Date:** 2026-05-25
**Status:** spec
**Parent:** integration-audit deferred backlog — "Broad refresher consolidation
(from B1c)" in `_handoff/RESUME.md` § "Deferred items"; meta doc
`docs/superpowers/specs/2026-05-19-integration-audit-meta.md`.

## What this is

The legacy per-slot cloud refreshers (`_refresh_cfg`, `_refresh_mihis`,
`_refresh_locn`, `_refresh_dock`, `_refresh_net`, `_refresh_dev`,
`_poll_slow_properties`) predate the CloudState architecture
(`project_cloud_state_architecture`, v1.0.0a100). `_refresh_cloud_state`
(every 2 min) now fetches the device's full state in one orchestrated call and
its `_apply_cloud_state_to_mower_state` already ports MIHIS + per-map SETTINGS
onto `MowerState`. The legacy timers were left running "pending a future
consolidation pass" — the docstring at `coordinator/_cloud_state.py:83-86`
says so verbatim. This is that pass.

The work removes the genuinely-redundant timers, folds the still-needed port
logic into the single 2-min path, and removes a latent clobber bug surfaced
during design.

**Out of scope (kept, with justification documented in Block D):**
`_refresh_locn` / `_refresh_dock` (60 s fast cadence; `_refresh_dock` also
feeds the state machine), `_refresh_net` (1 h; not in CloudState),
`_refresh_dev` (6 h; not in CloudState), `_poll_slow_properties` (1 h; feeds
the state machine + handles the s1.5 serial-while-unknown path).

## Decisions (user, 2026-05-25)

- **Scope: maximal.** Drop `_refresh_mihis`; fold `_refresh_cfg`; AND stop the
  full-state fetch from double-fetching LOCN/DOCK (the 60 s timers own those).
- **Clobber trap: fix + split push-owned fields out.** The folded CFG port
  uses the safe updates-dict pattern (never writes `None` for an absent key)
  AND excludes the s6.2-push-owned fields (`pre_mowing_height_mm`,
  `pre_edgemaster`) entirely, giving CFG and the push non-overlapping ownership.
- **Remove the dead CloudState fields.** Once LOCN/DOCK are no longer fetched
  into CloudState and nothing reads `CloudState.locn` / `CloudState.dock`,
  excise both fields from the dataclass rather than leaving them permanently
  empty.

## Background facts verified during design

- `CloudState` (`cloud_state.py:110-128`) already carries `cfg`, `mihis`,
  `locn`, `dock`, `mapl`, `settings`, `maps_by_id`, `props`. `net` and `dev`
  are **not** fields.
- `fetch_full_cloud_state` (`cloud_client/_fetchers.py:314`) populates `cfg`
  via the same `self.fetch_cfg()` call `_refresh_cfg` uses — so `cs.cfg` is
  shape-identical to what the CFG port consumes today. It probes LOCN/DOCK/
  MAPL/MIHIS at `_fetchers.py:508-527`.
- `_apply_cloud_state_to_mower_state` (`_cloud_state.py:150-206`) already
  applies `cs.mihis` (totals) and per-map SETTINGS, using the updates-dict
  pattern. It explicitly does **not** port CFG keys yet (note at L199-201).
- `_refresh_mihis` (`_refreshers.py:510-554`) duplicates exactly the MIHIS
  port already in `_apply_cloud_state_to_mower_state`, at a slower (10 min)
  cadence.
- `_refresh_cfg` (`_refreshers.py:104-487`) ports ~50 CFG fields onto
  `MowerState` via `dataclasses.replace(self.data, field=var)` for **every**
  field unconditionally (vars default to `None`), then polls MAPL via
  `_apply_mapl`. The unconditional replace clobbers any field whose CFG key is
  absent to `None`.
- `pre_mowing_height_mm` / `pre_edgemaster` are owned by the s6.2 push
  (`mower/property_mapping.py:114,117`) and surfaced as entities
  (`sensor_map.py:225-227`, `select_global.py:65`). On g2408 the CFG `PRE`
  list is length 2, so `_refresh_cfg`'s `>=3` / `>=9` branches never fire and
  it resets these two fields to `None` on every 10-min tick — an **active bug**
  fighting the push. (Confirmed g2408 `PRE` shape in
  `_refreshers.py:203-224`.)
- `_apply_mapl` (`_mqtt_handlers.py:87-141`) sets `_active_map_id`; the
  CloudState path does **not** currently apply MAPL. The cold-start active-map
  detection today depends on `_refresh_cfg`'s trailing MAPL poll.
- `_refresh_mapl` (the method, `_refreshers.py:86`) stays — it is still called
  by `select_global.py:871` and the MQTT map-flip handlers
  (`_mqtt_handlers.py:305,654`). Only `_refresh_cfg`'s inline MAPL poll is
  removed.
- **Nothing** reads `CloudState.locn` or `CloudState.dock` (verified across
  the whole component; LOCN→MowerState goes through `_refresh_locn`,
  DOCK→MowerState + state machine through `_refresh_dock`).
- No test calls `_refresh_cfg` / `_refresh_mihis` / `_refresh_locn` /
  `_refresh_dock` directly. `_apply_cloud_state_to_mower_state` (12 refs),
  `_apply_mapl` (8), `_refresh_cloud_state` (8) are well covered. The CFG-port
  logic has **no** direct test today.

## Block A — Drop `_refresh_mihis` (fully redundant)

`_apply_cloud_state_to_mower_state` already applies `cs.mihis` →
`total_mowed_area_m2` / `total_mowing_time_min` / `mowing_count` every 2 min.

- Remove the `_periodic_mihis` timer + immediate fire (`_core.py:451-463`).
- Delete `_refresh_mihis` (`_refreshers.py:510-554`).
- No port code to move — it already exists in the cloud_state path.

**Result:** MIHIS totals refresh at 2 min instead of 10; one fewer standalone
timer + RPC.

**Tests:** confirm (add if missing) a test asserting the cloud_state path sets
the three MIHIS fields from `cs.mihis`.

## Block B — Fold CFG port + MAPL into cloud_state, drop `_refresh_cfg` (the trap)

1. **New pure helper** `cfg_to_state_updates(cfg: dict) -> dict[str, Any]` in
   `coordinator/_property_apply.py` (the pure-function module). Updates-dict
   pattern: a field is added **only** when its CFG key is present and decodes
   cleanly; malformed values are logged and skipped (never crash). Ported keys:
   CMS (the three wear percentages), CLS, VOL, LANG (code + two indices), DND,
   PRE[0]=`pre_zone_id` / PRE[1]=`pre_mowing_efficiency`, WRP, LOW, BAT, LIT,
   ATA, REC, FDP/STUN/AOP/PROT, MSG_ALERT, VOICE. The decode logic moves
   **verbatim** from `_refresh_cfg` (per the audit rule: move bodies as-is).
   - **Excluded (push-owned):** `pre_mowing_height_mm`, `pre_edgemaster`. The
     helper must not emit these keys — they belong to the s6.2 push path.
2. `_apply_cloud_state_to_mower_state` merges `cfg_to_state_updates(cs.cfg)`
   into its existing `updates` dict (then the single `dataclasses.replace`).
3. **MAPL into the cloud path.** Add `self._apply_mapl(cs.mapl)` to
   `_refresh_cloud_state`, ordered **before** `_apply_cloud_state_to_mower_state`
   so `_active_map_id` is fresh when the SETTINGS/CFG port reads it. This makes
   cold-start single-pass (today it needs `_refresh_cfg`'s trailing MAPL poll).
   - `_apply_mapl` on an active-map *change* itself calls
     `_apply_cloud_state_to_mower_state` + `_sync_map_subdevices` + a render +
     listeners. Ordering it first means the subsequent explicit
     `_apply_cloud_state_to_mower_state` is at worst idempotent. The
     implementer must verify no double-broadcast regression in
     `test_active_map_routing` / `test_startup_availability`.
4. Remove the `_periodic_cfg` timer + immediate fire (`_core.py:387-397`);
   delete `_refresh_cfg` (`_refreshers.py:104-487`). Keep `_refresh_mapl`.

**Tests (TDD — write first, they fail against current code):**
- Unit tests for `cfg_to_state_updates`: present key → field set; absent key →
  key not in dict (caller leaves prior value); `pre_mowing_height_mm` /
  `pre_edgemaster` never emitted even when PRE is long; malformed value
  (e.g. `CMS` non-numeric) skipped without raising.
- Extend `_apply_cloud_state_to_mower_state` tests to assert CFG fields land on
  `MowerState` from `cs.cfg`.
- Assert active-map detection now happens via the cloud_state path
  (`_apply_mapl(cs.mapl)` sets `_active_map_id`).
- Regression test for the fix: a `MowerState` with a push-set
  `pre_edgemaster=True`, then a cloud_state refresh whose `cfg` lacks the
  field, must leave `pre_edgemaster` unchanged (today's code would null it).

## Block C — Dedup LOCN/DOCK in `fetch_full_cloud_state` + remove dead fields

1. In `fetch_full_cloud_state` (`_fetchers.py`): remove the `fetch_locn` and
   `fetch_dock` probe blocks (L508-517). Remove `locn=` / `dock=` from the
   `CloudState(...)` constructor (L530-546). Keep the `fetch_mapl` +
   `fetch_mihis` probes (both consumed by the folded path).
2. Remove the `locn` and `dock` fields from `CloudState`
   (`cloud_state.py:124-125`).
3. Update every other `CloudState(...)` construction site to drop the kwargs:
   - `tests/integration/conftest.py:203-204` (`make_empty_cloud_state` base).
   - `tests/test_cloud_state_dataclasses.py:25-26,41`.
   - `tests/integration/test_coordinator_writes.py:60,126`.
   - `tests/integration/test_startup_availability.py:69-70`.
   - `tests/integration/test_cloud_state_entity_attrs.py:51`.
   - `tests/integration/test_cloud_state_sensors.py:43`.
   - `tests/integration/test_settings_switch_entities.py:60`.
   - `tests/integration/test_settings_active_follower_rebind.py:125-126`.
   - `tests/protocol/test_fetch_full_cloud_state.py` — `_make_client` helper
     (L19) takes `locn=/dock=`; update the helper + any probe assertions.
4. **Audit-test fixups (verify, don't assume):**
   - `tests/audit/test_discover.py:72` uses `coord.cloud_state.dock.get(...)`
     as a **string literal** fed to a path classifier — not a real field
     access, so it won't break, but retarget the example to a surviving field
     (e.g. `cloud_state.mihis` / `cloud_state.cfg`) so it isn't misleading.
   - `tests/audit/test_fake_coord.py:26` references "CloudState.dock starts as
     empty dict" — inspect and update the fake/comment accordingly.

**Result:** ~1 fewer RPC/min; no field on `CloudState` that is never read.

**Tests:** `fetch_full_cloud_state` no longer calls `fetch_locn` / `fetch_dock`
(mock assertion); LOCN/DOCK `MowerState` fields still update via their 60 s
timers (existing `_refresh_locn` / `_refresh_dock` behavior unchanged).

## Block D — Comment sweep + docs + fact-discipline

- Fix stale "10-min" cadence comments now that the live cadence is 2 min:
  `_mqtt_handlers.py:117,123,301,622,649`, `_core.py:514`. Also drop the
  now-inaccurate "every 10 minutes" wording in the removed-timer neighbours.
- Rewrite the `_refresh_cloud_state` docstring (`_cloud_state.py:78-90`):
  remove the "remaining legacy refreshers … remain scheduled pending a future
  consolidation pass" sentence; state that CFG + MIHIS + MAPL are folded and
  list the timers that intentionally remain.
- Add a **"Refresher cadence"** subsection to
  `custom_components/dreame_a2_mower/CLAUDE.md` documenting the surviving
  timers and why (cloud_state 2 min = full state incl. cfg/mihis/mapl/settings;
  locn 60 s + dock 60 s = fast cadence, dock also feeds the state machine; net
  1 h; dev 6 h; slow_poll 1 h). Goal: a future session does not re-flag this as
  redundant.
- **Fact-discipline:** the source of `pre_edgemaster` / `pre_mowing_height_mm`
  changes (was CFG-clobbered + s6.2-push → now s6.2-push only). Append a
  `verifications:` entry to `entity-inventory.yaml` for the affected entity
  (`sensor.dreame_a2_mower_map_N_pre_edgemaster`, id at `entity-inventory.yaml:156`)
  recording the source correction, `status: verified`, evidence
  `mower/property_mapping.py:114,117`. Update `status.last_seen` to today.

## Testing gate

Full suite via the vanilla stubbed-HA venv (per `reference_test_env_setup`):
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests -q`.
Baseline before this work: **1591 passed, 4 skipped**. Net count rises by the
new characterization/unit tests; no pre-existing test may regress.

## Execution

Subagent-driven (`subagent-driven-development`), serial, each task a fresh
agent with the 2-stage review (spec adherence, then code quality):

1. **A** — drop `_refresh_mihis` (independent, low-risk).
2. **C** — LOCN/DOCK dedup + dead-field removal (independent of A/B,
   mechanical but wide test edit).
3. **B** — CFG fold + MAPL into cloud_state (the trap; heaviest review,
   includes the clobber-fix regression test).
4. **D** — comment sweep + docs + fact-discipline.

A and C are mutually independent and may run in either order; B depends on
neither but is sequenced last among the code changes so its review has the
final tree. D is documentation/cleanup over the finished code.

**Conventions** (from `_handoff/RESUME.md` working rules): commits prefixed
`audit-b1-refresher:`, authored as the user, **no** co-author trailer, on
`main`. Push only with explicit in-message authorization. `release.sh` pytest
preflight must be pointed at `.venv-vanilla` (bare `python3` is broken 3.14).
Move refactored bodies **verbatim**; prune imports only via per-name grep,
never by "tests pass".
