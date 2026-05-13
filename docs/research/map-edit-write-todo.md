# Map-edit write surface — research TODO

> **Status — UNKNOWN.** Last attempted 2026-05-13.
>
> Writing exclusion zones, ignore-obstacle zones, spots, and maintenance
> points from the integration is **not yet possible**. The MQTT routed-
> action surface that handles every other write (CFG, SETTINGS, SCHEDULE,
> task ops) **does not route map-edit opcodes**.

## What works today

| Type | Read | Write status |
|---|---|---|
| Exclusion zones (red, `forbiddenAreas`) | ✓ MAP.0..N decode | ✗ not implemented |
| Ignore-obstacle zones (green, `notObsAreas`) | ✓ MAP.0..N decode | ✗ not implemented |
| Spots (`spotAreas`) | ✓ MAP.0..N decode | ✗ not implemented (op=103 *triggers* a spot mow but doesn't *create* one) |
| Maintenance points (`cleanPoints`) | ✓ MAP.0..N decode, surfaced as per-map sensor | ✗ not implemented; sensor.py explicitly marks read-only |

## What we tried

`tools/probe_add_maintenance_point.py` (2026-05-13) sent the
`siid=2 aiid=50` routed-action TASK envelope for o:204 (begin edit), then
o:234 (save geometry) with four candidate payload shapes for a new
maintenance point on Map 2, then o:201 (commit). **Every call returned
HTTP 400** at `/device/sendCommand`. Same rejection class as the op=109
cruise-to-point probe — the cloud endpoint doesn't route these opcodes
from us via this transport.

Payload shapes tested (all rejected):

```json
A: {map_id:1, id:999, ids:[], type:9, shapeType:1,
    path:[{x:5000, y:5000}], angle:0}
B: {id:999, ids:[], type:9, shapeType:1,
    path:[{x:5000, y:5000}]}
C: {map_id:1, type:9, shapeType:1,
    path:[{x:5000, y:5000}], angle:0}
D: {map_id:1, cleanPoints:{value:[[999, {...}]]}}
```

## Likely actual write surface

The MQTT echoes for o:204 → o:234 → o:201 fire **after** the app saves a
zone in the Dreame app's map editor. Two plausible mechanisms:

1. **Separate HTTP endpoint** — the app POSTs the new geometry to a
   `/map/edit` / `/region/save` style endpoint (not exposed in any of
   the cloud_client surfaces we've reverse-engineered). The server
   applies the change and emits the MQTT echoes server-side. **This is
   the leading hypothesis.** Confirming requires HTTPS MITM of the
   Dreame app during a real map-edit operation.

2. **`setDeviceData` chunked write of MAP.0..N** — the app uploads the
   modified MAP blob via the same surface we already use for SETTINGS /
   SCHEDULE / AI_HUMAN. The MQTT echoes are server-driven notifications
   after the cloud parses the new geometry. We have **not** attempted
   this because corrupting MAP.0 risks bricking the boundary geometry
   (per `cloud-write-reference.md` Phase 2 note). Would need:
   - A map-backup mechanism (`fetch_map` already pulls the canonical
     state; `_maps_cache_store` from v1.0.8a4 provides a recent disk
     copy).
   - Round-trip parity tests: re-encode an unmodified MAP blob and
     diff against the original to confirm our encoder is byte-stable
     before attempting incremental edits.

## Recommended next steps (in order)

1. **HTTPS MITM of the Dreame app** during a map-edit operation
   (Charles / mitmproxy / Frida). Look for endpoints OTHER than
   `iotuserdata/setDeviceData` and `iotuserdata/getDeviceData` —
   anything `/map`, `/region`, `/zone`, `/clean-point`, or similar.
   Capture the full request body for a known edit (e.g., "add a
   maintenance point at known x/y on Map 2"). If found, this is the
   write surface.

2. **If no HTTP endpoint surfaces:** try the `setDeviceData` MAP write
   path on the sacrificial Map 2. Re-encode MAP.0..N with a single
   added `cleanPoints` entry, write it back via `write_chunked_key`,
   then poll `fetch_map` to confirm the new point sticks. Risk: high
   without a re-encode parity test.

3. **Whichever surface ends up working:** wire write APIs into the
   integration with safety guards — refuse writes during IN_SESSION,
   show a "may damage map" disclaimer, snapshot the pre-write MAP
   blob to `_maps_cache_store` for rollback.

## Files / opcodes referenced

- `tools/probe_add_maintenance_point.py` — the probe used 2026-05-13.
- `docs/research/cloud-write-reference.md` § "TBD (Phase 2/3)" —
  `MAP.0..N` flagged NOT TESTED.
- `docs/research/inventory/generated/g2408-canonical.md` § "o:234
  save_zone_geometry" — confirms the echo format (id, ids, no
  geometry).
- `custom_components/dreame_a2_mower/sensor.py` —
  `DreameA2MaintenancePointsSensor` explicitly marks the sensor
  read-only.
