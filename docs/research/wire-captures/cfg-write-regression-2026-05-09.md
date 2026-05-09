# CFG-write regression — wrong wire format (2026-05-09)

**Severity:** HIGH — silently broken since the integration shipped. Every CFG-backed entity reports HA writes as "successful" but the device rejects the routed-action with `r=-3` (not supported).

## Symptom

- HA toggles `switch.dreame_a2_mower_child_lock` ON.
- HA UI updates to `on` (optimistic).
- HA log: NO warnings — `set_cfg` returns True.
- Cloud `CFG.CLS` UNCHANGED (stays 0).
- Cloud `CFG.VER` UNCHANGED (no save event).
- No `s2p51` MQTT push fires (would normally fire on a real CFG change).
- App still shows "child lock off" — the user's setting was lost.

## Root cause

The integration's `cloud_client.set_cfg` (and the rest of the CFG-write surface) sends the wrong wire format for the routed-action set call.

### Wrong (current code)

```python
payload = {"m": "s", "t": KEY, "d": value}     # bare value
client.action(siid=2, aiid=50, parameters=[payload])
```

Cloud response (HTTP code=0, success), but the device's routed-action result inside `out` is:

```json
{"out": [{"m": "r", "q": 79, "r": -3}], "code": 0, ...}
```

`r=-3` means "method not supported / wrong format". The integration's `set_cfg` only checks the top-level `code`, never inspects `out[0].r`, so it returns True. **Every CFG-backed write has been silently failing this way.**

Probed against all 16 known-writable CFG keys: **all 16 return r=-3** with the bare-value format.

### Correct (the fix)

```python
payload = {"m": "s", "t": KEY, "d": {"value": value}}    # wrap value in {"value": ...}
client.action(siid=2, aiid=50, parameters=[payload])
```

Cloud response — confirmed working live 2026-05-09 15:11 against `CLS`:

```json
{"aiid": 50, "code": 0, "out": [{"d": {"value": 1}, "m": "r", "q": 36, "r": 0}], "siid": 2}
```

`r=0` = device accepted. `d={"value": 1}` = device echoed back the value it now has. CFG.CLS subsequently read as `1`. CFG.VER bumped 487 → 488.

Repeated round-trip 0 → 1 → 0: each direction produces `r=0` and a CFG.VER bump (487 → 488 → 489).

## Open question — does cloud-write drive the device firmware?

The cloud `CFG.<KEY>` value updates after T4 (correct format). What's NOT yet established:

- **Did the device firmware actually apply the change?** No `s2p51` push fires after our write (whereas app-side saves DO emit s2p51). Two interpretations:
  - The device firmware applies the change but doesn't echo s2p51 because s2p51 is reserved for UI-driven changes only.
  - The cloud just stores the value without notifying the device — i.e. cloud is a cache, not a write-through to the device.

The behavioral test: HA writes a CFG value via T4 → user cold-starts a fresh app instance → does the cold-started app reflect the new value? If yes, the cloud at least propagates to other clients. Whether the *device* applies the change is a separate question (some settings are easy to verify behaviorally — e.g. VOL plays at the new volume; CLS locks the mower; FDP changes frost-protection behavior — others are hard to test directly).

## Untested alternative write paths

The probe also tested `setDeviceData` with `CFG.CLS` and bare `CLS` keys (the chunked-batch surface used for SETTINGS / AI_HUMAN / SCHEDULE). Both returned `{'code': 0, 'success': True, 'msg': '设置成功'}` — but the test ran AFTER T4 had already changed CLS to 1, so we can't tell if T5/T6 are real or just no-ops. **Deferred:** isolate-test setDeviceData for CFG keys, see if it's a viable alternative.

## Impact on the audit

- All 16 CFG-backed entities have a write path that's broken in the same way — ALL write rows in the matrix flip from `⚠ untested` to `✗ HA-write surface broken (wrong wire format) — fix in coordinator/cloud_client`.
- The fix itself is small (wrap the value in `{"value": ...}`).
- The fix needs to be verified by an HA toggle + cloud diff + cold-start app, ideally for ≥2 representative entities.
- Once fixed, all 16 CFG-backed entities should be re-T4'd to confirm the fix works for the whole class.

## Code location

- `custom_components/dreame_a2_mower/cloud_client.py:set_cfg` — wraps the value into `{"m": "s", "t": KEY, "d": value}` (wrong)
- `custom_components/dreame_a2_mower/cloud_client.py:set_cfg` checks only top-level `code`, missing `out[0].r`

## Suggested fix structure (Phase 2)

1. Change `set_cfg` payload to `{"m": "s", "t": KEY, "d": {"value": value}}`.
2. After receiving the response, parse `out[0].r` and treat any non-zero `r` as failure (with the message logged).
3. For complex shapes (lists), the wrapping might differ — probe each shape (list[3] DND, list[6] BAT, etc.) before bulk-fixing.
4. Re-test all CFG-backed entities under the new path.

## Cross-reference

- This finding is the same class as the SETTINGS / AI_HUMAN / SCHEDULE write-uncertainty: cloud accepts the write at HTTP layer, but the actual routed-action result inside the response is what determines whether the device received it. The integration's success-detection logic is shallow across the board.
- The historical "BT-only" classification likely partially reflected this — some CFG writes were attempted, returned (HTTP) success, but didn't actually drive the device. That looked like "BT-only" but is really "wrong wire format".
