# Non-mow session capture (head-to-maintenance-point runs)

**Date:** 2026-05-30
**Status:** design — pending user review → implementation plan

## Problem

A scheduled edge mow on 2026-05-30 19:00 produced a single replay session that
actually contained **four distinct activities**: three earlier manual
"head to maintenance point" runs (16:49 failed on a garden hose, 16:59 and 17:25
succeeded) plus the edge mow. The trail data is captured correctly — paths render,
even the failed traversal — but all four are glued into one archive entry.

Two root causes:

1. **No type distinction.** The live-map session grabber starts a session on any
   `task_state` activity (s2p56 `[[_,0/4]]`), which fires for mows and
   head-to-point runs alike. Everything is labelled `[Mowing]`.
2. **Finalize never completes for point runs → merge.** A mow finalizes by waiting
   for the cloud OSS mow-summary (md5). A head-to-point run produces **no** cloud
   summary (0 area, blades up the whole time), so the finalize wait never resolves,
   `live_map` stays "active", and the next run just keeps appending — even across
   docking. (Verified: the mower *did* dock between each run, e.g. 17:23:41
   `s2p1=6` + charging; the merge was purely the md5 wait, not a missing dock.)

The goal: capture head-to-point runs as their own sessions, in the **same** archive
and picker (rendering already works), with a non-`[Mowing]` label and 0-area
handling.

## What the wire actually offers (verified, 9-log corpus)

- **No positive "head-to-point started" signal exists.** A mow emits `s2p2=50`
  (manual) / `53` (scheduled) "mowing task started"; a point run emits no equivalent.
  (`s2p2=30` at every point-start this afternoon was the wear reminder — confounded;
  it can't be the marker.)
- **s2p56 inner-array length does NOT distinguish them** (hypothesis refuted by
  corpus: inner-len 2 ends in mow 53× and point 8×; inner-len 3 is a mow sub-variant,
  not point). Two samples lied; 71 sessions corrected it.
- **The op (`s2p50` op=109 cruise vs 100-103 mow) is genuine but unreliable** — the
  app-triggered point moves and the *scheduled* edge mow both emitted **no** op echo
  on the status topic. Cannot depend on it.
- **The return leg is identical across types** (`s2p1=5` + movement + dock); only the
  trigger differs (71 standby / 48 complete / 54 low-battery). No type info there.
- **End codes** are present and exclusive-ish: point run ends `s2p2=75` (arrived) or
  `76` (cannot reach); mow ends `48` (complete).

## Design

### Classification — by presence of mow-evidence (positive, not end-code)

A run is classified at **finalize** (dock-return) by whether it ever showed
**mow-evidence**:

> **`session_type = mow`** iff the run ever saw `s2p2 ∈ {50, 53}` **OR**
> `area_mowed_m2 > 0`. **Otherwise `session_type = maintenance_run`.**

Rationale (why this over end-code, per review):
- It's a **positive** mow signal, not "absence of 75/76". A point run that fails
  mid-way and returns with **no** 75/76 still has no 50/53 and zero area → correctly
  `maintenance_run`. We never need the end code to type it.
- A **spot mow** traverses blades-up to the spot first (the false worry) but then
  lowers the blades (`area > 0`) and emits 50 → correctly `mow`.
- Both signals are reliably present for real mows across the corpus.

> **NOTE — the head-to-point start is INFERRED, not observed.** There is no positive
> "head-to-point started" code on the g2408 status wire. A `maintenance_run` is
> whatever active run reaches dock-return *without* having produced mow-evidence. If
> a future firmware/capture reveals a real start marker, prefer it and demote this
> rule to a fallback. (Recorded in `inventory.yaml` § s2p56 / s2p2 as well.)

### Boundary — finalize on dock-return (keeps the 3-leg run)

The session boundary is unchanged in spirit (trail is already captured until dock via
`_wait_for_dock_return`) but the **finalize trigger branches by type**:

- **`mow`** → existing path: wait for / merge the cloud OSS summary (md5), archive as
  today.
- **`maintenance_run`** → **new local-finalize path**: on dock-return, finalize
  **immediately** with no cloud wait (none is coming). This is the fix that splits the
  four merged runs.

A `maintenance_run` therefore spans all three legs — **out → idle-at-point → return →
dock** — exactly as observed (e.g. 16:59 arrive 17:01 → idle 20 min → return 17:21 →
dock 17:23).

### Archive fields

Add to the archive entry (raw_dict):

- `session_type: "mow" | "maintenance_run"` (default `"mow"` for back-compat with old
  archives that have no field; they were all mows).
- `outcome` (maintenance_run only): `"arrived"` (saw 75) | `"could_not_reach"`
  (saw 76) | `"unknown"` (neither — mid-run abort). Captures the garden-hose failure
  the user wants visible.

The live-map state tracks two booleans during the run (`saw_mow_start`,
`area_ever_positive`) and the last point-end code, resolved into the above at finalize.

### Picker label & card

- `session_card.format_session_label`: prefix by type — `[Mowing]` stays for mows;
  `maintenance_run` → **`[To Point]`** (generic; the destination is the maintenance
  point today but op=107/108 cruise-to-point may reuse this). Append the outcome for
  point runs, e.g. `[To Point] [Map 2] 2026-05-30 16:49 (blocked)` /
  `(arrived)`.
- The session card: when `session_type == maintenance_run`, suppress mow stats (area,
  coverage, mowing-time breakdown — all 0/N-A) and show a point-run summary instead
  (outcome, distance travelled, duration of the 3 legs). The trail still renders (it
  already does); legs are all traversal.

### Reserved future type — manual app driving (NOT implemented)

The app's manual-drive / joystick remote control (`s2p50` op=2/4/5/7 joystick in the
opcode catalog) is conceptually a session too, but **has never been seen on the wire**
in any capture. The `session_type` enum reserves a `"manual_drive"` value and the
classification leaves room for it (a manual-drive run would also show no mow-evidence;
a future positive marker — if joystick ops ever echo — would split it from
`maintenance_run`). No detection or handling is built now (YAGNI; unseen).

## Components touched

| Unit | Change |
|---|---|
| `live_map/state.py` | track `saw_mow_start` / `area_ever_positive` / last end-code; expose `session_type` + `outcome` resolution |
| `coordinator/_mqtt_handlers.py` | feed the mow-evidence signals (s2p2 50/53, area delta, 75/76) into live_map |
| `coordinator/_session.py` | branch finalize: local-finalize for `maintenance_run` on dock-return |
| `coordinator/_lidar_oss.py` | `_inject_live_map_into_raw_dict` writes `session_type` + `outcome` |
| `session_card.py` | `format_session_label` prefix + outcome; card 0-area / point-run summary |
| `inventory.yaml` | record the inferred-start note (s2p2 50/53 = mow marker; no point-start marker) |

## Testing

- Classification: fixtures for mow (sees 50/53 + area), point-success (no evidence,
  ends 75), point-fail (no evidence, ends 76), point-abort (no evidence, no end code) →
  assert `session_type` / `outcome`.
- Boundary: a captured/synthetic sequence of two point runs separated by a dock →
  assert two archive entries, not one (the regression for the 2026-05-30 merge).
- Label: `format_session_label` for each type/outcome.
- Back-compat: an old archive with no `session_type` reads as `mow`.
- Spot-mow guard: a blades-up-traverse-then-cut sequence classifies as `mow`.

## Out of scope

- Detecting/handling manual app driving (unseen — reserved only).
- Any change to how mows finalize (cloud-summary path untouched).
- Splitting two point runs that occur **without** an intervening dock (not observed;
  dock-return is the boundary).
</content>
