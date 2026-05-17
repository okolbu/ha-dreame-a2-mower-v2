# Replay Card Gap Behavior

## Purpose

Document how the Sessions-tab replay card behaves on sessions with trail
gaps. Closes `project_gappy_sessions_todo` from MEMORY.md. With Phase 1
of session-data-completeness in place, reboot-induced gaps should be
rare, but several gap classes remain legitimate (legitimate pause,
MQTT outage, dock-return-only-gap).

## Three gap classes

### 1. Reboot gap (should be rare post Phase 1)

**Trigger:** restart HA during an active mow.

**Expected behavior post-fix:** trail merges across the reboot. The
replay card animates continuously. The state-driven time breakdown
("Mowing", "Charging", "Rain", "Other") sums correctly with minimal
"Other" bucket. Validation: run a 10-min mow with a deliberate HA
restart at the 4-min mark; confirm the finished archive's sample
counts match probe-truth via `tools/state_partition.py`.

### 2. Legitimate pause gap

**Trigger:** press Pause in the app mid-mow, wait 5 min, Resume.

**Expected behavior:** trail shows a frozen-cursor span where the
mower didn't move. The animation's time-cursor advances through the
pause at the same wall-clock rate as the rest. No teleport jump.

### 3. MQTT-outage gap

**Trigger:** disconnect MQTT for 60s mid-mow (e.g., stop the
broker container briefly).

**Expected behavior:** trail has a visible spatial jump from the
last-pre-outage point to the first-post-outage point. The
animation's cursor traverses this jump as a straight line at
increased speed (distance / elapsed_time). The time-breakdown's
"Other" bucket slightly inflates by the outage duration.

## Pause-budget allocation

The animation engine concentrates `pauseBudgetMs` in `_local_legs`
gap boundaries (real pen-up moments at recharge/pause) rather than
`cloud_track_segments` fragmentation noise. The fix shipped in
v1.0.13a2; verified post-Phase-1 by re-running a known-pausing
session through the card.

## What to test before claiming this TODO closed

Pick one session from each of the three classes above and capture
a screenshot of the replay card's playback at three points:

- start (first frame)
- mid-gap (animation should still progress sensibly)
- end (last frame; dock-return arc should be visible per Phase 3)

If any of the three reveals genuine animation bugs (not just
expected gap rendering per the table above), open a new issue
rather than expanding this TODO's scope.

## Status

- 2026-05-17: doc written; live runs pending.
