# SETTINGS chunked-batch write surface — cloud-cache-only (2026-05-09)

**Severity:** HIGH — affects all 13 SETTINGS-backed HA entities. Same class of bug as the v1.0.2a9 set_cfg fix, but on a different cloud surface.

## Test method (T4, Task 4 of the protocol-validation audit)

1. Active map at test start: Map 2 (cloud `map_id=1`).
2. Cloud baseline: `entry0/map_id=1.obstacleAvoidanceAi = 7` (all 3 AI bits on); HA showed `ai_obstacle_recognition_humans = on, animals = on, objects = on`.
3. HA call: `switch.dreame_a2_mower_ai_obstacle_recognition_humans → turn_off` via the WebSocket `call_service`.
4. The integration ran `coordinator.write_settings(map_id=1, field="obstacleAvoidanceAi", value=6) → cloud_client.write_chunked_key("SETTINGS", json_blob) → setDeviceData(SETTINGS.0..N + .info)`.
5. Cloud response: `{"code":0,"success":true,"msg":"设置成功"}` — write_chunked_key returned `(True, ...)`.
6. Cloud snapshot 5 s after: `entry0/map_id=1.obstacleAvoidanceAi = 6` (humans bit cleared) — write reflected in cloud cache. `entry1/map_id=1.obstacleAvoidanceAi = 6` too (write_setting writes both entries).
7. **User opened Dreame app on Map 2 — AI Obstacle Recognition still showed all 3 on (humans on)**, even after a full app restart.

## Conclusion

The `setDeviceData` chunked-batch surface for SETTINGS is **a cloud-side cache only** on this firmware:

- Writes are accepted at HTTP layer (`success: true`).
- Writes ARE persisted in the cloud chunked-batch dump (`entry0/map_id=N.<field>` reflects the new value).
- But the **device firmware does NOT receive or apply** the change.
- The Dreame app reads from a different source (most likely device-direct via MQTT subscription on the live property channels), so app-side display does NOT reflect HA's writes.

This is fundamentally different from the v1.0.2a9 CFG fix:

| Surface | Used by integration for | HA write actually drives device? |
|---|---|---|
| `set_cfg` routed-action `s2.50 m='s' t=KEY` | 9 simple-shape CFG keys (CLS, FDP, STUN, AOP, PROT, VOL, ATA, MSG_ALERT, VOICE) | **Yes** — verified 2026-05-09 by user app cold-test on CLS |
| `set_cfg` for int-list CFG keys (DND, LOW, WRP, BAT, LIT, REC, LANG) | r=-3 from cloud | **No** — cloud doesn't have setter |
| `setDeviceData` chunked-batch (SETTINGS, AI_HUMAN.0, SCHEDULE) | 13 SETTINGS-backed + AI_HUMAN + SCHEDULE | **No** — cloud-cache-only, device doesn't see |

## Implications for the audit

- All 13 SETTINGS-backed HA entities have a write path that **silently fails to drive the device**, just like the broken pre-v1.0.2a9 CFG path. After v1.0.2a5's "pre-write fresh-fetch" + dual-entry write fixes, the cloud cache stays internally consistent — but the device firmware never sees the change.
- The historical "BT-only" classification was directionally right *for the device-apply outcome* even though wrong about the BT mechanism. The device just doesn't apply via this cloud surface.
- **The 13 SETTINGS-backed write rows in the matrix flip to `✗` (cloud-accept, device-doesn't-apply).**
- The integration should make this visible: today the write reports success in HA. Recommended fix: surface a distinct "write went to cloud cache, device-side application unverified" tier in the entity-write logging, OR (better) actually fail the writes pending Phase 3 work.

## What about AI_HUMAN.0 and SCHEDULE?

Both go through `setDeviceData` too. Untested in this audit pass. But by the same pattern they're likely cloud-cache-only as well. Will explicitly test in Tasks 5 and 6.

## Phase 3 work — capture the device-write path used by the Dreame app

Same root cause as the int-list CFG keys: the Dreame app uses a write path the integration hasn't enumerated. The likely paths are MQTT direct command publish (via the `/cmd/` topic) or a different HTTP endpoint we haven't probed.

For maximum coverage, the HTTPS sniff of the app should capture:
- A toggle on the Mowing Settings page (covers all 13 SETTINGS-backed entities — same surface)
- A toggle on the Notifications/DND/etc. page (covers the 7 CFG int-list keys)
- A toggle on Capture Photos AI Obstacles (covers AI_HUMAN.0)
- A schedule edit (covers SCHEDULE)

A single sniff session covering 4-5 settings will likely identify the missing surface.

## Code locations affected

- `coordinator.write_settings` — sends to cloud cache; returns True on cloud-success even though device-side application is unverified
- `coordinator.write_ai_human_enabled` — same pattern (uses write_chunked_key)
- `coordinator.write_schedule` — same pattern
- `cloud_client.set_batch_device_datas` / `cloud_client.write_chunked_key` — the underlying cloud transport

## Cross-reference

- Companion finding for CFG: `cfg-write-regression-2026-05-09.md`
- Spec: `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md`
- TODO entry: Phase 3 — capture Dreame app write RPC (now broader scope: covers SETTINGS, AI_HUMAN, SCHEDULE, plus int-list CFG keys)
