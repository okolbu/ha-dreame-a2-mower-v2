# Live GPS tracking — open research

**Status (2026-05-12):** the `device_tracker.dreame_a2_mower_location`
entity does NOT track the live mower position. It is wired to the
LOCN routed-action which only returns the **configured dock origin**
— not live tracking data.

## What we confirmed

During an active mow (mower moving in the back garden, app showing
live GPS on its own map):

- `cloud_client.fetch_locn()` returned `{pos: [-1, -1]}` — the
  "dock origin not configured" sentinel.
- HA's `device_tracker.dreame_a2_mower_location` stayed `unavailable`.
- The app continues to show fresh GPS coordinates updating roughly
  every ~10 minutes.

LOCN is therefore the dock-GPS-anchor slot, set by the user via the
app's "Set dock GPS" flow. On this mower that flow was never
completed, so LOCN returns the sentinel forever — even with
anti-theft realtime location toggled on.

## What we don't know

Where the cloud serves the **live mower coordinates** from. Three
plausible paths to probe:

1. **MIoT property poll.** The ~10 min update cadence matches our
   `_refresh_cloud_state` bulk poll. There's likely an `siid.piid`
   pair carrying decimal degrees. Probe by:
   - Enumerating all properties for the g2408 MIoT spec.
   - Looking for fields with values like `59.948…` (Norway) or
     similar plausible decimal-degree ranges.
   - Cross-checking against TA2k's `ioBroker.dreame` adapter for
     any `Lat`/`Long`/`gpsLat` property identifiers.

2. **Different routed-action type.** Try `t: 'GPS'`, `t: 'POS'`,
   `t: 'LOC'`, `t: 'TRACK'`. The cfg-action probe framework already
   supports arbitrary `t` values — extend
   `tools/inventory_probe.py` to enumerate plausible candidates.

3. **Computed locally.** Once LOCN's dock GPS is configured, the
   mower's cartesian position (from session telemetry: mm relative
   to dock) plus the dock GPS gives live mower GPS via the
   standard earth-radius approximation:
   ```
   lat = dock_lat + (y_mm / 1_000) / 111_320
   lon = dock_lon + (x_mm / 1_000) / (111_320 × cos(dock_lat))
   ```
   The integration already extracts cartesian position from session
   data for the cloud-frame map rendering. Combining the two only
   needs the dock GPS to be set in the app.

## Code state

- `device_tracker.py` uses `RestoreEntity` so once we DO get a
  live coordinate, the marker persists across restarts and outages.
- `_periodic_locn` polls every 60 s. Cadence is fine; the endpoint
  is wrong.
- `_attr_icon = "mdi:robot-mower"` is set so when coords flow, the
  pin renders as a mower silhouette.

## Easy unblock

The user can complete the "Set dock GPS" flow in the Dreame app.
That alone unblocks path 3 (computed) AND makes the LOCN-as-dock-
origin reading useful for the map (the dock pin would always be
correct, the mower would just look stationary at the dock between
sessions).

## What NOT to do

- Don't poll LOCN faster — the rate isn't the issue, the endpoint is.
- Don't add fallback logic in `device_tracker.latitude` to use the
  cartesian position alone (no GPS reference → no real lat/lon).
- Don't change the `available` gate to "always" — the entity must
  go unavailable if there's nothing to report, otherwise HA's map
  card shows a stale marker as if it's live.

## When to revisit

Pick this up when:
- A live MQTT capture is available during a mow (probe_a2_mqtt.py
  output for cross-correlation with app GPS updates), OR
- The user runs the dock-GPS-set flow and we can test path 3.
