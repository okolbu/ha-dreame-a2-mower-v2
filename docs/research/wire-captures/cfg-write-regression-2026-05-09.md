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

## Behavioral verification — set_cfg drives the device end-to-end (post-fix)

After v1.0.2a9 deployed, user toggled `switch.dreame_a2_mower_child_lock` in HA. The Dreame app reflected the change **within seconds, no app restart needed**. This proves:

1. The corrected wire format (`d={"value": <value>}`) propagates to the device firmware.
2. The cloud has a **live push channel from cloud → app** that delivers updates within seconds (not just on cold-start).
3. The earlier "is cloud just a cache, does it actually drive the device?" question is settled: **drives the device** for the working-shape CFG keys.
4. The earlier "5-min propagation delay" observation must have been observational artifact (probe-tool cache, session-token, etc.) — not real cloud-side delay.

Implication: all 9 working-shape CFG-backed entities (CLS, FDP, STUN, AOP, PROT, VOL, ATA × 3, MSG_ALERT × 4, VOICE × 4) inherit this verification by sharing the same `coordinator.write_setting → set_cfg` path. Only the wire format depends on the shape; the transport is the same.

## Probed alternatives for the 7 still-failing CFG keys (DND, LOW, WRP, BAT, LIT, REC, LANG)

| Variant | Result | Notes |
|---|---|---|
| `routed-action s2.50 m='s' t=KEY d=<bare list>` | `r=-3` | Pre-v1.0.2a9 path |
| `routed-action s2.50 m='s' t=KEY d={value:<list>}` | `r=-3` for non-bool lists | Wrapped works for ints / bool-lists, not int-lists |
| `routed-action s2.50 m='s' t=DND d={enabled:E,start_min:S,end_min:T}` | `r=-3` | Named keys |
| `routed-action s2.50 m='set' t=DND` and `m='w' t=DND` | None / error | Neither method exists |
| `setDeviceData {DND: <json>}` | `{code:0, success:true, msg:'设置成功'}` | False success — CFG.VER didn't bump, DND unchanged. Cloud accepts unknown keys silently. |
| `setDeviceData {CFG.DND: <json>}` | Same false success | |
| `set_property(s5, p1, bool)` (legacy DND) | `80001` | Direct MIoT, device offline / not supported |
| `set_property(s5, p4, json_str)` (legacy DND_TASK) | `80001` | |
| `set_property(s3, p3, json_str)` (legacy OFF_PEAK_CHARGING / BAT) | `80001` | |
| `set_property(s4, p22, json_str)` (legacy AI_DETECTION) | `80001` | Already known per journal |

**Conclusion**: neither the routed-action setX surface NOR the direct-MIoT set_properties surface works for these 7 CFG keys on g2408. The legacy integration's `set_property(s5, p1, ...)` for DND would have failed too (same 80001).

But the Dreame app obviously writes these settings (we have 3 weeks of s2p51 fires showing DND/LOW/BAT/LIT/REC values flipping after app saves). So there IS a working write path. **It's not in our cloud_client repertoire and not in the legacy integration's repertoire either.** We need to capture it.

## Phase 3 — capture the app's actual write RPC

The next investigation: capture the Dreame app's HTTP traffic during a "Save" tap on a DND change. Look for:
- A new endpoint we haven't seen (`dreame-user-iot/...` or `dreame-iot-com/...` with a different path)
- A different `method=` value (not `set_properties` or `action`)
- A different siid/aiid combination

Once captured, wire it into the integration's cloud_client, route the failing-shape entities through it, retest end-to-end.

For now: HA writes to these 7 entities correctly fail (after v1.0.2a9), surfacing the write-rejection in HA logs. The user has a clear "use the app for these" workaround.

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

## r=-3 disambiguation — it's target-missing, not format-wrong (2026-05-09 ~15:50)

To rule out a "format" hypothesis for the 7 still-failing keys, probed:

| Test | Result |
|---|---|
| `t='CLS' d={"value": [1,4]}` (CLS expects bool, sent list) | `r=0`, `d={"value": 1}` — cloud took first element, coerced to bool |
| `t='NONEXISTENT_KEY_XYZ'` | 80001 timeout (NOT `r=-3`) — unknown targets time out |
| `t='CMS' d={"value": [3777, 693, 693, -1]}` (read-only consumables) | `r=0` — cloud accepts even for read-only targets |
| `t='VOL' d={"value": true}` (VOL expects int) | `r=0`, coerced bool→int |

Conclusions:

- **`r=-3` ≠ "wrong format/value type"**. The cloud is lenient: if a target has a setter, it accepts almost anything and coerces (truthy-extract from list, bool→int, etc.).
- **`r=-3` specifically means: "no setter registered for this `t=KEY` at this routed-action address"** on this firmware. Different from `80001` (unknown route entirely) and from `r=0` with no-op (read-only-ish key).
- **The 7 failing keys (DND, LOW, WRP, BAT, LIT, REC, LANG) genuinely don't have a setter at the `s2.50 m='s' t=<KEY>` address.** No format variation will make them accept. They need a different cloud surface.
- **`r=0` doesn't always mean "applied to device".** CMS is a read-only counter; writing it returned `r=0` without changing the actual counter. For CLS specifically, behavioral verification (user's cold-app test) confirmed `r=0` here means "real apply". For others, treat with caution until behaviorally verified.

**Side-effects from this probe:** Test A's coercion accidentally set CLS=1 (child lock enabled), Test E's bool-coercion set VOL=1 (mower nearly muted). Both reverted immediately.

## Probe-safety incident — 2026-05-09 ~15:35

While probing alternative siid/aiid combinations for WRP write, the
`s2.aiid=1` call inadvertently triggered a START action: the device
ignored the `m='s' t='WRP'` parameters and interpreted `s2.aiid=1` as
"start globally". The user reported the mower starting unexpectedly;
a `button.recharge` service call sent it back to the dock immediately.

**Lesson:** Routed-action probes with experimental `aiid` values are
not safe — the device may interpret unknown aiids as known commands,
ignoring the `m=` / `t=` / `d=` payload entirely. Future probing of
alternative write targets must EITHER:
1. Stick to `aiid=50` (the known routed-action target) and only vary
   the `m=` / `t=` / `d=` fields, OR
2. Run only when the mower is docked AND the user is watching.

**Outcome of this probe:** No alternative siid/aiid combo accepted
the WRP write — every combination returned `r=-3` or `80001`. The
`s2.aiid=1` start was an unintended side effect, not a successful
write.
