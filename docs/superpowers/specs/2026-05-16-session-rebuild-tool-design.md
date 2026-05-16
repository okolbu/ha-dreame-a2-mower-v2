# Session Rebuild Tool — Design

**Date:** 2026-05-16
**Status:** Draft (pending user review)
**Supersedes:** `tools/backfill_session_samples.py` (4-stream subset)

## Problem

The 2026-05-15 19h session showed the cost of HA-restart-driven
data loss in `in_progress.json`: 8.5 h of telemetry samples lost,
manifesting in v1.0.14a8 as a 519-min "Other" bucket that should
have been ~6 min. The same probe log captured the full session —
2-3× more events than the integration archive (battery 217 vs 641,
state 19 vs 31, etc.).

Until the [[project-session-persist-audit-todo]] root-cause work
fixes the persist chain, we should be able to reconstruct any
"looks broken" session by replaying probe-captured MQTT events
against the integration's wire decoders. The existing
`tools/backfill_session_samples.py` does 4 of the 5 sample arrays
in bulk-only mode and doesn't touch wifi/legs/charge_at_start/
settings_snapshot.

## Goals

A new `tools/rebuild_session.py` that:

1. **Covers every backfillable field** in the session JSON spec —
   sample arrays, `legs`, `wifi_samples`, `charge_at_start`,
   `settings_snapshot`. (Cloud-only fields like `md5`,
   `area_mowed_m2`, `obstacles` are preserved from the existing
   archive if present, otherwise left empty.)
2. **Single-session AND bulk modes.**
3. **Probe `*.jsonl` files are the source of truth** for *which*
   sessions exist — the bulk mode walks probe logs to find session
   boundaries via `s2p56` task_state transitions, then pulls the
   matching HA archive (if any), backfills, and pushes back.
4. **Surfaces uncovered sessions** — if HA has a session archive
   that no probe log covers, the tool lists it under "no info on
   these" so the operator knows it can't be rebuilt.
5. **HA-direct fetch and push** (via SCP, behind a `--dry-run`
   flag), unlike the existing tool which expects pre-staged JSONs
   in a local directory.
6. **Verbose per-stream diff** — "battery_samples: 217 in archive
   → 641 in probe → +X added → 380 final" so the operator can see
   what improved.

## Non-goals

- Inventing cloud-only fields (`md5`, `area_mowed_m2`,
  `map_area_m2`, `obstacles`). Preserve existing values; leave
  empty when creating a new archive from scratch.
- Fixing the underlying persist bug. That's
  [[project-session-persist-audit-todo]].
- Rewriting the wire decoders. Reuse `protocol/heartbeat.py`,
  `protocol/_telemetry.py` (or whichever module owns the s1p4
  decode), and `protocol/session_summary.py` directly.
- Real-time / always-on operation. This is an operator-triggered
  diagnostic, not a coordinator-side process.
- Generating maps / images. Just the JSON.

## Architecture

```
                            tools/rebuild_session.py
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
   ProbeReader                   HAArchiveFetcher              SessionRebuilder
  (walk *.jsonl,            (SCP /config/dreame_a2_mower/      (per-session:
   build event store         sessions/<name>.json,             merge probe events
   indexed by slot           push back via SCP)                 into archive,
   and timestamp)                                              port wire decoders
                                                                offline)
                                       │
                                       ▼
                              VerboseDiffReporter
                              (per-stream counts + decision)
```

Three pure-Python modules (or one tool file with internal classes
— implementer's call):

- **ProbeReader** — given a glob, scans all probe logs, builds an
  event store indexed by `(siid, piid, ts)`. Reused for both
  bulk-mode session detection AND per-session backfill.
- **HAArchiveFetcher** — SCP read/write with a dry-run flag.
  Lists existing session JSONs; pulls one by filename; pushes back
  with a `.tmp` swap.
- **SessionRebuilder** — operates on one session window:
  - Loads existing archive (if any).
  - For each backfillable field, computes the new value by
    replaying probe events through the integration's decoders.
  - Returns a new session dict + per-stream diff stats.

## Source of truth: which sessions to rebuild

**Bulk mode:** walk all probe `*.jsonl` files, extract `s2p56`
task_state transitions, and emit one `(start_ts, end_ts)` pair per
session. Per inventory.yaml, `s2p56` carries
`{"status": [[task_type, sub_state]]}`:

- `prev ∈ {None, 2}` and `new == 0` → session start at this ts
- `prev ∈ {0, 4}` and `new ∈ {2, None}` → session end at this ts

For each detected window:
1. Locate matching HA archive (filename pattern
   `<date>_<end_ts>_*.json`).
2. If found: `rebuild(archive, probe_events_in_window)`.
3. If not found: synthesize a new archive from probe events alone,
   filename `<date>_<end_ts>_rec_<hash8>.json` (matches the
   existing `rec_*` convention).

**Single-session mode:** `--session-start <ts>` finds the matching
window in probe data (within ±300 s tolerance to handle clock
skew), then proceeds the same way.

**Uncovered sessions:** at end of bulk mode, list HA archives
whose `start_ts` falls outside ALL probe-derived session windows.
These can't be rebuilt; the report highlights them so the operator
knows to either start a probe earlier or accept the archive as-is.

## What gets backfilled

| Field | Source | Notes |
|---|---|---|
| `start`, `end` | probe `s2p56` transitions | Existing archive's values preferred (more authoritative than probe-derived) |
| `battery_samples` | probe `s3p1` | Existing tool's logic, dedup on `(ts, value)` |
| `charging_status_samples` | probe `s3p2` | Same pattern |
| `state_samples` | probe `s2p1` | Same |
| `error_samples` | probe `s2p2` | Same |
| `wifi_samples` | probe `s1p1` heartbeat (RSSI byte) + most-recent s1p4 position | Replay `protocol/heartbeat.decode_s1p1` and pair with last position |
| `legs` | probe `s1p4` (position) + `s2p56` (begin_leg boundaries) | Replay `protocol/_telemetry.decode_s1p4` + leg-start logic from `live_map.LiveMapState.append_point` |
| `charge_at_start` | most-recent `s3p1` BEFORE start_ts | Existing tool's logic |
| `settings_snapshot` | probe `s5p107` / `s6p1` / `s2p51` at-or-before start_ts | Latest value per slot, captured into a dict matching the live `settings_snapshot` shape |
| `md5` | preserved from existing archive | Cloud-only; if creating new, `f"rec_{hash8(start_ts, end_ts)}"` |
| `area_mowed_m2` | preserved | Cloud-only |
| `map_area_m2` | preserved | Cloud-only |
| `obstacles` | preserved | Cloud-only (from OSS) |

## Modes & CLI

```
tools/rebuild_session.py [OPTIONS]

Modes (mutually exclusive):
  --session-start TIMESTAMP   Single session at this start ts (epoch seconds
                              or ISO8601). Tolerates ±300s clock skew when
                              matching against probe-derived windows.
  --bulk                      Walk all probe files, rebuild every session
                              found.
  (default: bulk)

Options:
  --probe-glob PATTERN        Glob for probe logs.
                              [default: /data/claude/homeassistant/probe_log_*.jsonl]
  --tz ZONE                   Timezone for probe timestamps.
                              [default: Europe/Oslo]
  --ha-host HOST              SCP host.
                              [default: read from /data/claude/homeassistant/ha-credentials.txt]
  --ha-sessions-dir PATH      Remote sessions directory.
                              [default: /config/dreame_a2_mower/sessions]
  --dry-run                   Compute backfill, print diff, but DON'T scp back.
  --no-overwrite              Skip sessions whose archive already has all
                              streams >= probe coverage (no improvements
                              possible).
  --json-out PATH             Write per-session diff stats as JSON to this
                              file in addition to stdout.
  -v / --verbose              Increase verbosity.
```

## Output format

Per session:

```
=== Session 2026-05-15 16:00:00 (1778889600 → 1778893682) ===
  archive: 2026-05-15_1778893682_7bff1b02.json (308995 bytes)
  probe events: 6680 in window across 8 slots
                                  archive  probe   added  final
  battery_samples                     217    641     380    597
  charging_status_samples               9     17       8     17
  state_samples                        19     31      12     31
  error_samples                        10     18       8     18
  wifi_samples                        458   1234     245    703
  legs                                  3      5       2      5
  charge_at_start                      85     85       -     85  (matches)
  settings_snapshot                  18 keys 19 keys  +1     19
  decision: copy back to HA (35 new datapoints across 6 streams)
```

If no improvements:

```
=== Session 2026-05-15 16:00:00 (1778889600 → 1778893682) ===
  archive: 2026-05-15_1778893682_7bff1b02.json (308995 bytes)
  probe events: 6680 in window
  All streams already >= probe coverage. Skipping copy-back.
```

End-of-bulk summary:

```
=== Summary ===
Sessions in probe windows: 47
  Backfilled (improvements found): 31
  Skipped (no improvements): 14
  Failed (decode error): 2

Sessions in HA archive with NO probe coverage (can't rebuild): 12
  /config/dreame_a2_mower/sessions/2026-04-17_1776456578_0ae4c4b4.json
  /config/dreame_a2_mower/sessions/2026-04-18_1776541055_0a68d124.json
  ...
```

## Testing

**Unit tests** (in `tests/tools/test_rebuild_session.py`):

- Session-window detection from synthetic probe events
  - Single happy-path session (None → 0 → 2 → None).
  - Multiple sessions in one log.
  - Mid-log start (probe began with mower already running).
  - Mid-log end (probe truncated mid-session — no `2`/`None`).
- Per-stream backfill on a synthetic event store
  - 4 sample arrays (mirror existing tool).
  - `wifi_samples`: heartbeat with valid RSSI + position-changed pair.
  - `legs`: position points + `s2p56` `4 → 0` transition causes new leg.
  - `charge_at_start`: most-recent s3p1 before window start.
  - `settings_snapshot`: latest s5p107 wins.
- Diff reporter
  - Empty archive (no improvements).
  - Improvement on one stream only.
  - All streams improved.
- Cloud-field preservation
  - `md5`, `area_mowed_m2` preserved when archive exists.
  - `md5 = "rec_<hash>"` when creating from probe alone.

**Smoke test** (manual, against the 19h session probe log + archive):

- Run `tools/rebuild_session.py --session-start 1778824800 --dry-run`
- Expect ~+424 battery samples, +12 state, +8 error, +245 wifi,
  +2 legs.
- Re-run `tools/state_partition.py` against the rebuilt session
  and confirm "Other" drops from 519 min to <50 min.

## Risks

1. **Decoder coupling.** The tool imports `protocol/heartbeat.py`
   and `protocol/_telemetry.py` (or whatever owns s1p4 decoding).
   If those evolve, the tool may need updating. Acceptable —
   protocol decoders evolve slowly and the tool is operator-only.

2. **Probe log file format drift.** The probe captures
   `mqtt_message` events with `payload.data.params` for
   `properties_changed`. If the wire format changes (e.g.
   `params[i].value` becomes a different shape), the tool needs
   updating. Mitigation: a smoke test on the 19h session in CI
   would catch any regression.

3. **Bulk-mode session boundary detection.** A session that began
   before the probe started OR ended after the probe stopped will
   look "open" in the probe data. We can either drop these
   incomplete windows (safe) or attempt to align with HA archive
   start/end timestamps (more aggressive). Recommend dropping
   incomplete windows in v1; revisit if it filters out useful
   sessions.

4. **Re-fetching cloud-only fields.** If the existing archive's
   `obstacles` field is empty (cloud OSS fetch failed at finalize),
   this tool can't fill it. The operator would need to re-trigger
   a finalize cycle separately. The tool documents this limitation
   in its `--help` output.

5. **WiFi sample debounce mismatch.** The live integration's
   `append_wifi_sample` has a 25cm-radius dedup. The rebuild tool
   should apply the same dedup so the reconstructed list matches
   what the live coordinator would have produced. Use the same
   helper, not a re-implementation.

6. **Leg boundary detection from probe alone.** Live integration
   triggers `begin_leg` on `task_state_code 4 → 0` transition. The
   rebuild tool needs to read s2p56 transitions and apply the same
   logic. The single source of truth is
   `coordinator/_session.py` — port the boundary logic into a
   pure helper or import the relevant function.

## Out of scope

- Reconstructing maps (PNGs) or LiDAR scans. The tool only
  rebuilds the JSON metadata.
- Recovering sessions from before the probe corpus exists. By
  definition no info available; report and skip.
- Cross-session deduping (e.g., the same MQTT event appearing in
  multiple probe files due to log rotation). Use `(ts, slot, value)`
  as the dedup key — same as the existing tool.
- Migration of the existing `tools/backfill_session_samples.py`.
  The new tool supersedes it; delete the old tool in the same PR
  that ships the new one (or keep with a deprecation notice for
  one release cycle — operator's choice).

## Acceptance criteria

- Running `tools/rebuild_session.py --session-start 1778824800`
  on the 19h session produces a session JSON with `state_samples`
  count ≥ 31 (up from 19), `error_samples` ≥ 18 (up from 10),
  `battery_samples` ≥ 380, `wifi_samples` ≥ 700, `legs` ≥ 5.
- After backfill, `tools/state_partition.py` shows "Other" < 50
  min for the same session (down from 519 min).
- Bulk mode against the existing probe corpus produces a summary
  listing per-session diff stats and the "no info" sessions.
- Cloud-only fields (`md5`, `area_mowed_m2`, `map_area_m2`,
  `obstacles`) are preserved unchanged when the archive exists.
- `--dry-run` prints the same per-session output as a wet run but
  doesn't scp anything back.
- All unit tests pass.

## Related

- `2026-05-16-session-recorder-merge-and-rain-bucket-design.md` —
  recorder-merge safety net (Part 1, shipped v1.0.14a7) was the
  finalize-time complement to this offline tool.
- `2026-05-16-state-driven-time-breakdown.md` — state-driven
  breakdown (shipped v1.0.14a8) made the data loss VISIBLE in
  user-facing numbers, which is what triggered this rebuild
  tool's design.
- [[project-session-persist-audit-todo]] — root-cause work for
  the underlying persist bug. Once that lands, this tool becomes
  a debugging-only utility rather than a load-bearing recovery
  path.
- [[reference-iobroker-write-paths]] — TA2k's adapter is the
  reference for any wire-format ambiguities.
