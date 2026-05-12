# Cruise-to-Point (op=109) — research TODO

**Status (2026-05-12):** opcode identified, send-envelope unknown.
Parked.

## What we know

From MQTT capture during an app-driven "Head to Maintenance Point"
tap (point→point, mower already off-dock), the cloud's echo on the
status topic was:

```
s2p50 = {"t": "TASK", "d": {"o": 109, "exe": true, "status": true,
                            "error": 0, "estimate_time": 60,
                            "time": 10664}}
```

So **op=109 = cruise-to-point** on the s2.50 TASK envelope pipeline.
Same as our integration's existing op=100/101/102/103 (mow / edge /
zone / spot).

Device-side lifecycle, also captured:
- `s2p56 = {status:[[N, 0]]}` — task N starting, stage 0
- ... cruise telemetry via s1p1 / s1p4 ...
- `s2p56 = {status:[[N, 2]]}` — task N arrived, stage 2
- `s2p1 = 2` — task_state done
- **`s2p2 = 75`** — event "arrived_at_maintenance_point"
- `s1p52 = {}` — session-end marker

The notification synthesizer already fires the arrival event via the
s2p2=75 hook — no integration change needed on the read side.

## What we tried — all rejected

`tools/probe_cruise_to_point.py` exercised 20 combos against the
cloud `/device/sendCommand` endpoint (the path that successfully
handles op=100/101/102/103 mowing actions):

- **4 envelopes** × **5 d-shapes**:
  - envelopes: `{m,p,o,d}` minimal; `+t:TASK`; `+t:TASK,exe:true`;
    `m:'s'` set-mode
  - d-shapes: `{tpoint:[[x,y,0,0]]}`, `{point:[[x,y]]}`, `{point:[id]}`,
    `{cleanPoints:[id]}`, `{target:{x,y}}`
- **Every single combo returned HTTP 400** "Bad Request" with body
  pointing at `/device/sendCommand`.

The 400 is an HTTP-layer reject at the cloud — before the request
ever reaches the device. So the issue isn't the d-shape; it's that
this endpoint doesn't route op=109.

## Why a brute-force probe is unlikely to succeed

- Tried 5 plausible d-shapes drawn from legacy code (`tpoint`), spot
  envelope conventions (`area`/`point` by id), and MAP blob key
  names (`cleanPoints`). All fail.
- The cloud may require:
  - A different aiid (not 50) for this op
  - A different siid altogether
  - A different cloud HTTP endpoint (the Dreame app rotates between
    several — partial captures in `proxyman/` show
    `eu-central-1.api-iot.aliyuncs.com` early in the session, but
    other endpoints appear later)
  - Signed-request headers (`x-ca-signature`, `x-ca-nonce`, HMAC)
    that the integration doesn't currently produce

None of these are guessable from outside.

## What would unblock this

Pick one:

1. **Successful cert-pinning bypass on the app**, then capture the
   exact HTTP request the app issues when "Head to Maintenance
   Point" is tapped. That gives us the endpoint + the full request
   body. Ongoing experiment per the user (2026-05-12).
2. **Decompile the apk** and find the action map that binds op=109
   to a specific endpoint / aiid / sign function. Tedious but no
   live-traffic dependency.
3. **A different reference implementation** that already has
   cruise-to-point working on g2408 — none found so far. TA2k's
   ioBroker.dreame, the legacy ha-dreame-a2-mower-legacy, and the
   alternatives/dreame-mower (Tasshack) repos all use the MIoT
   `s4 aiid=1 START_CUSTOM` path, but that's a different cloud
   route untested on g2408. Worth trying as a fallback if Path 1/2
   stall, but the legacy MIoT route has been wrong on other actions
   for g2408 — low-confidence.

## What we are NOT going to do

- Keep adding more envelope/d-shape variants. The cloud HTTP layer
  is filtering before the device sees anything; more guessing wastes
  cycles.
- Implement the integration button on top of the legacy
  `s4 aiid=1 START_CUSTOM` route blindly. If we can't even
  empirically validate it works, shipping it as a feature is just
  another way to break user automations.

## Related code

- `tools/probe_cruise_to_point.py` — the empirical probe (20 combos)
- `custom_components/dreame_a2_mower/mower/actions.py` — TASK
  envelope library, ops 100/101/102/103/200/10 confirmed working
- `custom_components/dreame_a2_mower/cloud_client.py` line ~2151 —
  `routed_action` (the `s2.50` `{m,p,o,d}` builder)
- `custom_components/dreame_a2_mower/coordinator.py` `_fire_alert`
  hook + `s2p2=75` → already wires "arrived_at_maintenance_point"
  event when the action completes successfully (regardless of who
  initiated it)

## When to revisit

When (1) or (2) above produces a working capture / decompiled
endpoint, the implementation is straightforward:

1. Add `MowerAction.GO_TO_POINT` to the action enum
2. Add a `_go_to_point_payload(params)` function mirroring
   `_zone_mow_payload` / `_spot_mow_payload`
3. Wire `coordinator.start_go_to_point(map_id, x_mm, y_mm)` →
   `dispatch_action(GO_TO_POINT, {...})`
4. Add a per-map `DreameA2HeadToMaintenancePointButton` in button.py
   that reads `MapData.maintenance_points` and calls the coordinator
5. Replace the dashboard's "Head to Maintenance Point (Plan 2)"
   placeholder with the real buttons

Until then: park.
