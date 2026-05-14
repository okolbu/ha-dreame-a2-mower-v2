# LiDAR Obstacle Recognition (per-map setting) — open research

**Status (2026-05-14):** Unmodeled. The Dreame A2 app exposes a
per-map toggle "LiDAR Obstacle Recognition" that is **distinct** from
the SETTINGS-payload `obstacleAvoidanceEnabled` field already wired
to `switch.<map>_lidar_obstacle_recognition` (v1.0.10a7 per-map
SETTINGS migration).

## What we know

- The toggle is per-map (the app shows different values for Map1 vs
  Map2 on the same robot).
- It does **not** map to any field in the per-map `SETTINGS` payload
  we currently poll (`cloud_state.settings.by_map_id_canonical[map_id]`).
- It's likely on a separate cloud slot or CFG endpoint that we don't
  yet poll.

## Next steps

1. **Sniff:** flip the toggle in the app while running
   `tools/cloud_dump.py --live` and diff the cloud responses before /
   after. Likely candidates:
   - A separate CFG.* key (analogous to `CFG.LMR` or `CFG.LDR`?).
   - A separate per-map settings slot (`mode != 0` in SETTINGS raw).
   - A method-call action that doesn't appear in poll output.
2. **Compare:** TA2k's `ioBroker.dreame` adapter doesn't model this
   either (g2408 firmware tier-2/3 negative per
   `project_g2408_iobroker_negatives` memory). So we're on our own.
3. **Wire:** once the slot is identified, add a per-map switch
   class following the pattern of `DreameA2ObstacleAvoidanceEnabledSwitch`
   in `switch.py`.

## Related entities

- `switch.<map>_lidar_obstacle_recognition` (currently the
  `obstacleAvoidanceEnabled` SETTINGS bit — see whether this is the
  same setting from a different angle).
- `switch.<map>_obstacle_avoidance_on_edges` (edgeMowingObstacleAvoidance).
- `switch.<map>_ai_recognition_humans/animals/objects`
  (obstacleAvoidanceAi bitmask).
