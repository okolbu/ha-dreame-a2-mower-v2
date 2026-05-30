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

A run is classified at **finalize** by:

> 1. **`manual_drive`** iff `s2p50 op=15` was seen (manual/remote control), else
> 2. **`mow`** iff the run ever saw `s2p2 ∈ {50, 53}` **OR** `area_mowed_m2 > 0`, else
> 3. **`maintenance_run`** (the default non-mow run).

(op=15 is checked first but is only present when the op echoes; a manual run with no
op echo falls through to rule 3 — acceptable.)

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

### Boundary — finalize on dock-return OR new task command

A session ends on **either**:
1. **dock-return** (the existing capture-until-dock via `_wait_for_dock_return`), or
2. **a new task command** while still off-dock — `s2p56` empties (`status: []`) then
   re-activates with a new target set, a new `s2p2 ∈ {50,53}`, or a new `s2p50` op.

Condition 2 is required: live 2026-05-30 the user abandoned a manual run **without
docking** (s2p1 1→2, mower idle on the lawn) and then started the spot mow from that
spot — no dock between them. Dock-only finalize would merge the manual run and the
spot mow. The new-command edge splits them. (A per-target arrival `s2p2=75` inside a
queued multi-target run is NOT a new command — the queue lives in one `s2p56` list —
so it does not split.)

The **finalize trigger then branches by type**:
- **`mow`** → existing path: wait for / merge the cloud OSS summary (md5).
- **`maintenance_run` / `manual_drive`** → **new local-finalize path**: finalize
  immediately with no cloud wait (none is coming). This is the fix that splits the
  four merged maintenance runs (each *did* dock between, so condition 1 already
  applies; the cloud-md5 wait was the only thing blocking finalize).

A `maintenance_run` spans all three legs — **out → idle-at-point → return → dock** —
exactly as observed (16:59 arrive 17:01 → idle 20 min → return 17:21 → dock 17:23).

### Archive fields

Add to the archive entry (raw_dict):

- `session_type: "mow" | "maintenance_run" | "manual_drive"` (default `"mow"` for
  back-compat with old archives that have no field; they were all mows).
- `outcome` (maintenance_run only): `"arrived"` (saw 75) | `"could_not_reach"`
  (saw 76) | `"unknown"` (neither — mid-run abort). Captures the garden-hose failure
  the user wants visible.
- `target_ids` (targeted runs — point runs, and later zone/spot/edge mows): the
  **ordered sequence of s2p56 task_ids** (first element of `status[0]`) visited during
  the session. **One app command can queue multiple items run in order** (e.g. point 1
  then point 2, or zone A then B), so the task_id changes through the excursion and a
  per-target arrival (`s2p2=75`) is a **waypoint, not a session end** — the session is
  still the whole excursion to dock-return. Verified 2026-05-30: the four *separate*
  point runs (docked between each) read task_id `2,1,1,2` — a stable per-point id (it
  repeats, so not a session counter), matching the user's `A,B,B,A` recollection. The
  id is NOT the app's display number; the **display "Point N" is resolved by
  cross-referencing the active map's point list** (presumably creation order — the
  user was guessing the 1-vs-2 labels). Store the raw id sequence (dedup consecutive
  duplicates); resolve display numbers at render time from the map data.
- `mow_type` (mow only): `all_areas | edge | zone | spot` — from the **cloud OSS
  summary `mode`** field, which is the op code: **`100`=all_areas, `101`=edge,
  `102`=zone, `103`=spot** (decoded 2026-05-30 across 10 past summaries). Plus
  `start_mode`: **`1`=scheduled, `0`=manual/app** — store it too (free
  scheduled-vs-manual signal). Both are firmware-produced and present even when the
  MQTT `s2p50` op does not echo. Store the raw ints alongside the decoded labels so it
  degrades gracefully. **Do NOT source mow_type from `MowerState.action_mode`** — that
  is the user's dropdown *intent for the next dispatch* (persistent, defaults
  `ALL_AREAS`), not a record of the session.

The live-map state tracks during the run: `saw_mow_start` (s2p2 50/53),
`area_ever_positive` (area delta > 0), the last point-end code (75/76), and the
`target_id` (s2p56 task_id, latched at first-active). These resolve into the fields
above at finalize; `mow_type` is merged from the cloud summary on the mow path.

### s2p56 structure (what we learned)

`s2p56 = {status: [[task_id, stage], ...]}` — the status is a **list with one entry
per queued target**. Findings 2026-05-30:

- **Multi-target queue is the list** (live-confirmed on the 2-spot mow): the list
  holds one entry per target and **advances in-place** —
  `21:18:32 [[1,0],[2,-1]]` (spot 1 running, spot 2 queued) →
  `21:25:43 [[1,2],[2,0]]` (spot 1 **done** stage 2, spot 2 now running). Both entries
  persist the whole run; each target's stage advances independently
  (`-1` queued → `0` running → `2` done). So `target_ids = [entry[0] for entry in
  status]` read from any push, and per-target progress ("1 of 2 done") is free.
  Per-spot completion is the s2p56 **stage**, not an `s2p2` code (no s2p2 fired between
  the spots; `s2p2=48` fires once at the end of the whole mow).
- **`task_id`** (elem 0 of each entry) = stable per-target id — distinguishes which
  point / spot / zone / edge. The selector signal.
- An entry's length/stage changes through its lifecycle
  (`[1,0]→[1,0,0]→[1,0,2]→[1,2]→[1,4]`), so **length is not a stable type flag** (an
  earlier "2-part=point, 3-part=mow" idea was refuted: 2-part ends in mow 53× / point
  8×). mow_type comes from the cloud summary `mode` (or `s2p50` op when echoed), not
  from s2p56 shape.

### `s2p50` op echo — present for app-triggered, absent for scheduled

Live 2026-05-30: app-triggered runs **do** echo `s2p50` —
`op=103 area_id=[1,1]` (2-spot mow), `op=15` (manual). Scheduled mows and the earlier
app head-to-point moves did **not**. So when present, `s2p50` op gives the exact type
directly (100/101/102/103 mow subtypes, 109 cruise, 15 manual) and `area_id` the
region; use it opportunistically. Because it's unreliable, the **primary**
classification stays the mow-evidence rule, with op/summary as enrichment. (Note:
`area_id=[1,1]` looks region-scoped — both spots in region 1 — while the per-spot ids
`[1, 2]` come from s2p56; prefer s2p56 task_ids for `target_ids`.)

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

### Third type — manual app driving (`manual_drive`) — NOW OBSERVED

Captured live 2026-05-30 21:10: starting manual/remote control from the app rolled the
mower off the dock and emitted **`s2p50 op=15`** (`{"o":15,"status":true}` — the
opcode catalog's hypothesized "remote_setting", now confirmed as the manual-drive
start). With no driving input the mower stood idle (s2p1 1→2). So `manual_drive` is
**detectable** (op=15) when the op echoes, and otherwise looks like a non-mow run
(no 50/53, no area) — i.e. it falls into the same default bucket as a maintenance run
unless op=15 is seen. Plan: `session_type = manual_drive` when `s2p50 op=15` is seen;
else the mow-evidence rule applies (manual-with-no-op degrades to a generic non-mow
run, acceptable). Label `[Manual]`. Still light on data (one idle capture) — treat the
op=15 marker as `partial` until a second sighting, and keep the mow-evidence fallback.

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
