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

Where the cloud serves the **mower coordinates** from. GPS is
explicitly an **anti-theft** feature on g2408 — the user must
enable "send GPS from mower" in the app, and even then it reports
infrequently (only useful if the mower goes missing). Real lat/lon
are transmitted, NOT cartesian-relative-to-dock.

## Negative results (2026-05-12)

During an active mow with `switch.anti_theft_realtime_location = on`:

- Scanned the entire day's MQTT archive (628 messages across
  `s1p1, s1p4, s1p50, s1p51, s1p53, s2p1, s2p2, s2p50, s2p51, s2p56,
  s2p62, s3p1, s3p2, s5p106, s6p3`). NONE of them contained the
  known home lat/lon in any encoding tested:
  - int32 × 10⁶ (LE/BE)
  - int32 × 10⁷ (LE/BE)
  - float32 (LE/BE)
  - float64 (LE/BE)
  - decimal string (`"59.94..."`)
- Sole MQTT topic in the archive: `/status/<did>/<sn>/dreame.mower.g2408/eu/`.
  All payloads use `method=properties_changed`. The integration's
  `mqtt_client.py` subscribes to exactly that one topic (the cloud
  hands it via `cloud_client.mqtt_topic()`).

So GPS is **NOT** on the `/status/` MQTT channel we subscribe to.

## Plausible paths (research)

1. **Separate MQTT topic.** Anti-theft might publish to
   `/anti-theft/<did>/...`, `/locate/<did>/...`, or
   `/event/<did>/.../gps`. The cloud's `mqtt_topic()` RPC currently
   returns only one topic; check if there's a way to enumerate or
   request additional subscriptions (e.g., a `subscribe_topics`
   RPC).
2. **Dedicated cloud RPC.** Try routed-action types
   `t: 'GPS' | 'POS' | 'TRACK' | 'ALERT' | 'LOCATE'`. The cfg-action
   probe framework supports arbitrary `t` values; extend
   `tools/inventory_probe.py` to enumerate plausible candidates and
   see which one returns non-sentinel data.
3. **Cross-reference TA2k's `ioBroker.dreame`.** Grep their codebase
   for `gps`, `latitude`, `longitude`, `anti-theft` paths. Most
   likely already named in their adapter since the g2408 anti-theft
   feature predates this integration.
4. **App network capture.** As a last resort, MITM the Dreame app's
   HTTPS traffic and look for the polling endpoint that updates
   the GPS map.

## What we already know NOT to be the path

- **LOCN** routed-action: returns `pos: [-1, -1]` (dock-origin
  sentinel) even during an active mow. Always wrong endpoint for
  live tracking.
- **`/status/` MQTT**: zero GPS-shaped values across hundreds of
  messages per day.
- **Cartesian + dock origin composition**: not viable on g2408
  because the cloud serves real GPS for anti-theft, not derived
  from cartesian. Even if we tried, the dock-origin slot (LOCN) is
  unconfigured.
- **HTTP session boosting MQTT**: ruled out (2026-05-12). Integration
  (HTTP + MQTT) and external probe (MQTT only) see byte-identical
  payloads at the same timestamps on the same `/status/` topic.
  In a 15h overlapping window: integration 628 msgs, probe 618 msgs,
  per-slot counts within ±10 across all 15 slots. The cloud
  doesn't gate MQTT distribution on having an HTTP session.
  Consequence: the integration's daily raw-MQTT archive at
  `/config/dreame_a2_mower/mqtt/` was disabled to avoid duplicating
  the probe's output; re-enable in `_init_mqtt` only when the probe
  is off.

## Code state

- `device_tracker.py` uses `RestoreEntity` so once we DO get a
  live coordinate, the marker persists across restarts and outages.
- `_periodic_locn` polls every 60 s. Cadence is fine; the endpoint
  is wrong.
- `_attr_icon = "mdi:robot-mower"` is set so when coords flow, the
  pin renders as a mower silhouette.

## No easy unblock

The earlier "set dock GPS in the app" idea no longer applies — the
g2408 doesn't compose GPS from cartesian+dock; it has a separate
anti-theft GPS reporter. Configuring the dock origin would make
the dock pin work (a stationary marker at the user's house) but
wouldn't help live-track the mower during a mow or after theft.

## What NOT to do

- Don't poll LOCN faster — the rate isn't the issue, the endpoint is.
- Don't add fallback logic in `device_tracker.latitude` to use the
  cartesian position alone (no GPS reference → no real lat/lon).
- Don't change the `available` gate to "always" — the entity must
  go unavailable if there's nothing to report, otherwise HA's map
  card shows a stale marker as if it's live.

## When to revisit

Pick this up when one of:
- Someone enumerates routed-action `t` types systematically and
  finds the GPS one.
- TA2k's adapter gets cross-referenced for the anti-theft path.
- An app-traffic capture identifies the cloud endpoint.

Until then, the `device_tracker.dreame_a2_mower_location` entity
remains `unavailable` and the GPS map card on the dashboard shows
the HA home-zone fallback. The user has been informed.
