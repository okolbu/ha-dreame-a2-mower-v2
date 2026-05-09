# ioBroker.dreame write-path catalog — findings for our integration (2026-05-09)

**Source:** `/data/claude/homeassistant/OLD/alternatives_archive_2026-05-05/ioBroker.dreame/` (recently synced; latest commit `fe0db96` v0.3.7, "fix SETTINGS chunking, fix mower actions"). Author has been actively working on the same g2408 mower since late April 2026 (commits `4a1696d` mower CFG remotes → `fe0db96` SETTINGS chunking).

**Why this matters:** ioBroker has **already solved** the wire-format puzzle for the 7 CFG keys our integration cannot write (`WRP/LOW/DND/LIT/CMS/PRE` plus an entire `AutoSwitch` write surface we missed). They send **named-key payloads** (`{value, time, sen, light, fill}`) instead of our wrapped-list approach. This is the breakthrough we were searching for.

**Disclaimer:** ioBroker's table is a code declaration, not a per-key live verification log. Each key still needs a live probe on g2408 before we ship a write. But the format gives us a strong starting hypothesis where today we have nothing.

---

## 1. CFG SET — what their table says

All CFG writes use the same envelope as ours: `siid:2 aiid:50 in: [{m: 's', t: KEY, d: <payload>}]`. The difference is the shape of the `d` payload.

`main.js:884-916` — table comment: *"Plugin SET commands via action channel (siid:2 aiid:50, m:'s'). Format: `{m:'s', t:cfgKey, d:{value:X}}` or `d:{value:X, time:Y, ...}`"*.

| CFG key | Our current `d` (always `{value: X}`) | ioBroker `d` payload |
|---|---|---|
| `WRP` Rain Protection | `{value: [enabled, hrs, sen]}` → r=-3 | `{value: 1, time: 8, sen: 0}` (on) or `{value: 0}` (off) |
| `LOW` Low-speed Night | `{value: [enabled, start_min, end_min]}` → r=-3 | `{value: 1, time: [1200, 480]}` or `{value: 0}` |
| `DND` Do Not Disturb | `{value: [enabled, start_min, end_min]}` → r=-3 | `{value: 1, time: [1200, 480]}` or `{value: 0}` |
| `LIT` Headlight | `{value: [list[8]]}` → r=-3 | `{value: 1, time: [480, 1200], light: [1, 1, 1, 1], fill: 0}` |
| `CMS` Reset Consumables | `{value: <single>}` | `{value: [0, brush, robot]}` (full 3-elem array; index set to 0 = reset) |
| `PRE` Mowing Preferences | (didn't have it) | `{value: <full PRE array with one slot replaced>}` (read-modify-write) |
| `FDP` Frost Protection | `{value: 0|1}` ✓ | same |
| `CLS` Child Lock | `{value: 0|1}` ✓ | same |
| `VOL` Volume | `{value: 0..100}` ✓ | same |
| `AOP` AI Obstacle | `{value: 0|1}` ✓ | same |
| `STUN` Anti-theft | `{value: 0|1}` ✓ | same |
| `PROT` Grass Protection | `{value: 0|1}` ✓ | same (we already have it; it's in our "working" list) |
| `PATH` Path Display | (didn't have it) | `{value: 0|1}` |

**Not in their table:** `BAT`, `LANG`, `REC`, `MSG_ALERT`, `VOICE`, `ATA`. They only enumerated the user-facing toggles. Our coverage of `MSG_ALERT/VOICE/ATA` exceeds theirs; `BAT/LANG/REC` are still unknown for both projects.

### The handler that constructs the payload — `main.js:3506-3565`

```js
// CFG SET command: {m:'s', t:cfgKey, d:{value:X}} or d:parsed JSON
const cfgKey = stateObjCfg.native.cfgKey;
let payload;
if (typeof state.val === 'string') {
  try { payload = JSON.parse(state.val); }   // ← user provides JSON; e.g. '{"value":1,"time":8,"sen":0}'
  catch (e) { return; }
} else {
  payload = { value: state.val };            // ← simple bool/int → wrapped
}
await this.sendMowerCommand(device, { m: 's', t: cfgKey, d: payload });
```

So the user types e.g. `{"value":1,"time":8,"sen":0}` into the WRP state, ioBroker parses and forwards it. **They have not exhaustively tested every combination either** — but the format is documented, presumably from the vendor app's HTTPS sniff.

---

## 2. PRE — the new (to us) read-modify-write CFG key

`main.js:910-915` declares the PRE indices for mower-specific preferences:

| Index | Field | Values |
|---|---|---|
| `PRE[1]` | Mow Mode | 0=Standard, 1=Efficient |
| `PRE[2]` | Cutting Height | mm |
| `PRE[5]` | Direction Change | 0=auto, 1=off |
| `PRE[8]` | Edge Detection | 0/1 |
| `PRE[9]` | Edge Mowing | 0/1 |

(`PRE[0,3,4,6,7]` not in their table.)

Write pattern (`main.js:3534-3544`): `getCFG → mutate one PRE slot → setCFG with full array`:

```js
const cfgResult = await this.sendMowerCommand(device, { m: 'g', t: 'CFG' });
if (cfgResult && cfgResult.d && Array.isArray(cfgResult.d.PRE)) {
  const pre = [...cfgResult.d.PRE];
  pre[stateObjCfg.native.preIndex] = Number(state.val);
  await this.sendMowerCommand(device, { m: 's', t: 'PRE', d: { value: pre } });
}
```

Our integration has `pre_*` *read* values inferred from the s6p2 multi-field but **no PRE write path**. This unlocks 5 new writable entities once verified.

---

## 3. AutoSwitch (siid:4 piid:50) — entirely new write surface

`main.js:904-909` and `3510-3516`. **Mower-side AutoSwitch keys observed:**

- `LessColl` — Collision Avoidance (0/1)
- `FillinLight` — Fill Light (0/1)
- `SmartHost` — CleanGenius (0/1/2)
- `CleanRoute` — Cleaning Route mode (1-4)
- `SmartCharge` — Auto Charging (0/1)

**Wire format** — `set_properties` (NOT an action), JSON-stringified `{k, v}`:

```js
const payload = JSON.stringify({ k: key, v: Number(state.val) });
await this.sendCommand({
  did: device.did,
  method: 'set_properties',
  params: [{ did: device.did, siid: 4, piid: 50, value: payload }],
});
```

This is a totally separate write channel from the routed `s2.50 m='s' t=KEY` we use everywhere else. We currently *read* `siid:4 piid:50` (it's the AutoSwitch JSON blob); we don't write to it. **Most likely candidates from our app inventory** that map to AutoSwitch keys: collision-avoidance setting, fill-light toggle. Worth diffing our app config against this list.

---

## 4. Action commands — which siid/aiid the ioBroker author has converged on

After painful trial-and-error (commits `74467a3` "remove dangerous start-zone-mow", `6263df1` "Fix mower return-to-dock siid:3 aiid:1 → siid:5 aiid:3"), v0.3.7 has settled on **direct MIoT actions**:

| Command | siid | aiid | params (`in`) |
|---|---|---|---|
| Start Mowing | 5 | 1 | `[]` |
| Stop Mowing | 5 | 2 | `[]` |
| Pause Mowing | 5 | 4 | `[]` |
| Return to Dock | 5 | 3 | `[]` |
| Custom Mow | 4 | 1 | `[10, 1]` (mode=10, category=1) |
| Clear Warning | 4 | 3 | `[]` |
| Shortcut start | 4 | 1 | `[{piid:1,value:25},{piid:10,value:scId}]` |
| Generate 3D map | 2 | 50 | `[{m:'a', p:0, o:10, d:{idx:0}}]` (routed) |
| Request WiFi map | 6 | 4 | `[]` |
| Find Robot (sound) | 2 | 50 | `[{m:'a', p:0, o:9}]` (routed) |
| Lock Robot | 2 | 50 | `[{m:'a', p:0, o:12}]` (routed) |

**For our integration:** Find/Lock/3D-map/wifi-map are entities we don't currently expose. Worth picking up — they need no new wire format, just new actions.

For start/stop/pause/dock our integration uses the **routed** path `s2.50 m='a' o=100..103` and it's working — ioBroker uses the **direct MIoT** path on siid:5/4. Both routes exist. Don't change ours.

> **Important warning from `74467a3`:** `siid:2 aiid:3 in:[4]` was treated as "start zone mowing" historically but **actually triggers RETURN-TO-DOCK** on g2408. Don't probe blindly.

The "remap siid:2 → siid:5 for mowers" rule is in `main.js:3611-3613` — the generic-action handler quietly upgrades any `siid:2` action call to `siid:5` when the device is a mower. This explains why their CFG `actionStates` table at `:919` says "siid:2 aiid:1" but the comment says "(5-1)" — the user-visible state has siid:2 but the actual wire call goes to siid:5.

---

## 5. SETTINGS chunking — same write-success / device-no-effect pattern as us

ioBroker's most recent commit `5d8ec1d` (Apr 28) is a **read** fix: SETTINGS/SCHEDULE come chunked (SETTINGS.0, SETTINGS.1, …) and parsing only the first chunk truncated at 1024 bytes. They did not solve the write problem — `main.js` does NOT contain a SETTINGS *write* code path. They expose SETTINGS as a read-only JSON blob.

**Implication:** ioBroker has not figured out how to make SETTINGS writes drive the device either. Our finding from `settings-surface-cloud-only-2026-05-09.md` (cloud-cache-only) is consistent with theirs. The Phase 3 sniff is still required for SETTINGS-backed entities.

---

## 6. Recommended actions for our integration

**Tier 1 — verify ioBroker's CFG complex-payload formats live (high likelihood, low risk):**

1. Build a probe that calls `set_cfg` with the named-key payload for one key at a time:
   - `WRP {value:1, time:8, sen:0}` — easiest test, single value space
   - `DND {value:1, time:[1200,480]}` — list inside named key
   - `LIT {value:1, time:[480,1200], light:[1,1,1,1], fill:0}` — full struct
2. Watch for `out[0].r=0` AND verify the change in app + on next CFG poll. If the named-key format works, refactor `set_cfg` to accept arbitrary `d` payloads (currently hardcodes `{value: value}`).
3. Plumb Home Assistant entities through with the right named-key shape.

**Tier 2 — new write surface: PRE preferences (5 new entities):**

- Implement read-modify-write PRE path: `getCFG`, mutate one slot, write `{m:'s', t:'PRE', d:{value: <full array>}}`.
- Indices to expose: PRE[1] mode, PRE[2] cutting height (mm), PRE[5] direction change, PRE[8] edge detection, PRE[9] edge mowing.

**Tier 3 — new write surface: AutoSwitch (5+ new entities):**

- New code path entirely: `set_properties [{siid:4, piid:50, value: '{"k":"<key>","v":<n>}'}]`.
- Mower keys: `LessColl, FillinLight, SmartHost, CleanRoute, SmartCharge`.
- Read side: parse the existing s4p50 AutoSwitch JSON to populate read-only sensors.

**Tier 4 — new actions (free, no new wire format):**

- `find_robot` (op=9), `lock_robot` (op=12) via existing routed-action wrapper.
- `generate_3dmap` (op=10 with `d:{idx:0}`).
- `request_wifi_map` direct MIoT `siid:6 aiid:4`.

**Defer:** The 13 SETTINGS-backed entities are still cloud-cache-only on both integrations. That gap stands and still needs the Phase 3 app sniff.

---

## 7. Quotable wire-format reference

Drop these into the next probe script — copy-paste exact:

```python
# CFG complex payloads — ioBroker hypothesis, not yet live-verified on g2408
WRP_ON  = {"value": 1, "time": 8, "sen": 0}     # rain-prot on, 8h wait, low sensitivity
WRP_OFF = {"value": 0}
DND_ON  = {"value": 1, "time": [1200, 480]}     # 20:00-08:00 in minutes
DND_OFF = {"value": 0}
LOW_ON  = {"value": 1, "time": [1200, 480]}     # same shape as DND
LOW_OFF = {"value": 0}
LIT_ON  = {"value": 1, "time": [480, 1200], "light": [1, 1, 1, 1], "fill": 0}

# CMS reset (zero one of [blade_min, brush_min, robot_min])
# Read CFG.CMS, set target index to 0, write back:
# {m:'s', t:'CMS', d:{value:[0, current_brush, current_robot]}}  # reset blade

# PRE write (read-modify-write)
# Read CFG.PRE, replace one slot, write back:
# {m:'s', t:'PRE', d:{value:[...full array with one slot replaced]}}

# AutoSwitch (different transport: set_properties not action)
# method='set_properties' params=[{siid:4, piid:50, value:'{"k":"LessColl","v":1}'}]
```

---

## Live-verification on g2408 (2026-05-09)

After cataloguing, each tier was probed against g2408 to determine which findings actually apply to this firmware. **Most of the catalog turns out to be vacuum-derived or applies to other Dreame mower models, not g2408.** Concrete verdict per tier:

### Tier 1 — CFG complex named-key payloads ✓ APPLIES

End-to-end verified live (cloud + Dreame app):

- `WRP {"value":<0|1>, "time":<hours>}` — accepted, device applies, app reflects (round-trip 4h→6h→4h with app live-tracking the change). The optional `sen` (rain-sensor sensitivity, `sen ∈ {0,1,2,3}`) is silently accepted but not echoed back in `getCFG` and not surfaced in the Dreame app on this firmware — omitted from our writes.
- `DND {"value":<0|1>, "time":[start_min, end_min]}` — accepted (cloud round-trip OK).
- `LOW {"value":<0|1>, "time":[start_min, end_min]}` — accepted (cloud round-trip OK).
- `LIT {"value":<0|1>, "time":[start, end], "light":[1,1,1,1], "fill":<0|1>}` — accepted (cloud round-trip OK).

**Important deviation from ioBroker's catalog**: the bare `{"value":0}` form they document for "off" is **rejected with r=-3** on g2408 — always send the full named-key form regardless of enabled bit.

Shipped in `feat(cfg): named-key wire format for WRP/DND/LOW writes` (commit `c2ab186`).

### Tier 2 — PRE preferences (read-modify-write) ✗ DOES NOT APPLY ON g2408

g2408's `CFG.PRE` is just a **2-element list `[0, 0]`** — not the rich multi-slot array ioBroker describes for other Dreame mowers (where PRE[2]=cutting-height-mm, PRE[8]=edge-detection, PRE[9]=edge-mowing). Round-trip writes return `r=-3` (no setter at this CFG key on g2408 firmware).

The corresponding entities on g2408 (cutting height, edge mowing, etc.) live behind the SETTINGS chunked-batch surface instead — see Phase 3 work item in TODO.md (the cloud-cache-only finding from `settings-surface-cloud-only-2026-05-09.md`).

### Tier 3 — AutoSwitch (`set_properties` siid:4 piid:50) ✗ DOES NOT APPLY ON g2408

`get_properties [{siid:4, piid:50}]` returns `80001 设备可能不在线` (device-offline error) — the property doesn't exist on g2408 firmware. The AutoSwitch surface is vacuum-side (and possibly newer mower firmware); on g2408 the equivalent toggles (CleanGenius / cleaning route / etc.) don't exist as user-facing options, so the read+write surface isn't there either.

### Tier 4 — new actions ✓ MOSTLY ALREADY COVERED

Cross-referencing ioBroker's action table against `mower/actions.py:ACTION_TABLE`:

| ioBroker action | Wire | Our `MowerAction` | Status |
|---|---|---|---|
| Find Robot (op=9) | s2.50 routed | `FIND_BOT` (op=9) | ✓ already have button |
| Stop Mowing | s5.aiid=2 / op=200-ish | `STOP` | ✓ already have |
| Pause Mowing | s5.aiid=4 | `PAUSE` | ✓ already have |
| Return to Dock | s5.aiid=3 | `DOCK` / `RECHARGE` | ✓ already have |
| Clear Warning (op=11) | s4.aiid=3 routed_o=11 | `SUPPRESS_FAULT` | ✓ already have |
| Lock Robot (op=12) | s2.50 routed | not in our enum (we treat lock as CHILD_LOCK = CFG.CLS toggle) | ⚠ deferred — ioBroker's op=12 is a distinct "lock robot from being moved" action, separate from CHILD_LOCK; semantics on g2408 unverified |
| Generate 3D Map (op=10 with `d:{idx:0}`) | s2.50 routed | not in our enum | ⚠ deferred — would need a new action shape supporting `d` payload |
| Request WiFi Map | s6.aiid=4 | not in our enum | ⚠ deferred — different siid/aiid routing |

**Net Tier 4 finding:** the four actions ioBroker exposes that we don't (op=12 lock, op=10 3dmap, s6.aiid=4 wifi-map) are nice-to-haves; adding them without live verification is risky and the mower can only be probed when docked. Deferred to a future session.

## Cross-references

- Companion finding (cloud-cache-only SETTINGS): `settings-surface-cloud-only-2026-05-09.md`
- CFG fix that landed v1.0.2a9: `cfg-write-regression-2026-05-09.md`
- ioBroker source: `/data/claude/homeassistant/OLD/alternatives_archive_2026-05-05/ioBroker.dreame/main.js` (commit `fe0db96`, 3921 lines)
- Audit spec: `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md`
