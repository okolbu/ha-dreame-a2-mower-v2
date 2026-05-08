# Cloud-write integration — design

**Status:** approved 2026-05-08, pending implementation plan
**Driver:** today's discovery that g2408's Dreame Cloud accepts arbitrary chunked-batch writes via the `dreame-user-iot/iotuserdata/setDeviceData` endpoint. Three keys verified writable end-to-end (AI_HUMAN.0, SCHEDULE.0, SETTINGS chunked); the 80001 wall the integration hit on direct `set_property(siid, piid, value)` is specific to MIoT-style writes, NOT this surface.

The integration today is read-only at the entity level: 15 SETTINGS-driven entities + the AI_HUMAN switch all dispatch through `_write_setting_placeholder` (logs + refreshes; no mutation). SCHEDULE has no edit path. This spec converts those to real read/write and adds a SCHEDULE edit card.

## Goal

Phase 1 of a staged-by-risk read/write integration:
- Wire the 15 existing SETTINGS-driven entities to actually write
- Wire the AI_HUMAN switch to actually toggle
- Add a SCHEDULE edit card with full per-plan add/edit/delete
- Build generic chunked-write infrastructure (chunker, lock, optimistic-update + revert pattern) so Phase 2 (MAP write) and Phase 3 (other chunked keys) snap in without architectural rework

## Phasing

| Phase | Scope | Risk | Status |
|---|---|---|---|
| **1 (this spec)** | SETTINGS + AI_HUMAN + SCHEDULE | low — all verified safe round-trip; entities already exist; impact of bad write is bounded (one parameter / toggle / plan) | **active** |
| 2 | MAP write — boundaries, mowing zones, exclusion zones | high — corrupting boundary geometry could brick the lawn map; needs auto-backup-before-write + restore mechanism | TODO |
| 3 | Other chunked keys (FBD_NTYPE, M_PATH, OTA_INFO, TASKID, prop.s_*) | per-key triage; some may be firmware-managed and unsafe to write | TODO |

Phase 1 deliberately includes only the verified-safe trio. Phase 2 and 3 each get their own brainstorm + spec.

## Non-goals

- MAP write surface (Phase 2)
- HA's native `schedule.*` helpers as the SCHEDULE UX surface (the cloud's per-action / per-zone fields don't map cleanly to HA's schedule helper model — custom card is the right primitive)
- Modeling EdgeMaster / Mowing Efficiency as cloud-writable. Historical doc (2026-05-06) documented these as `s6p2`-only / BT-only. Those claims **predate the cloud-discovery findings of 2026-05-08** and may be outdated; live-toggle correlation against the new known cloud surface is needed before either is wired into Phase 1's writable surface.
- Backwards compatibility for any current automation depending on the placeholder behavior (the placeholder logged + refreshed; real writes mutate. Documented as a breaking change in the release notes.)

## Architecture

### Layer 1 — `cloud_client.write_chunked_key`

The only place chunking + the `setDeviceData` endpoint live.

```python
def write_chunked_key(
    self,
    key_prefix: str,
    value: str,
    info: str | None = None,
) -> tuple[bool, dict | None]:
    """Write a chunked-batch value to the cloud.

    Splits `value` into ≤1024-char chunks (server-enforced cap), builds
    {"<prefix>.0": ..., "<prefix>.1": ..., "<prefix>.info": ...}, calls
    set_batch_device_datas. Returns (ok, raw_response).

    `info` defaults to str(len(value)) (matches the SETTINGS / SCHEDULE
    pattern observed live). Callers writing keys where .info carries
    something else (M_PATH offset, MAP split point) override.
    """
```

Returns the raw cloud response so coordinator-level callers can log + surface specific failure reasons. `set_batch_device_datas` itself is unchanged from today's bugfix.

### Layer 2 — coordinator lock + per-domain helpers

Single coordinator-wide `_chunked_write_lock: asyncio.Lock`. Each per-domain helper acquires the lock, does read-modify-write against `self.cloud_state`, calls `cloud_client.write_chunked_key`, releases. Single mutex (not per-blob) because cross-blob writes are rare and a single lock simplifies reasoning. Hold time per write is sub-second.

Three per-domain helpers:

| Method | Argument | Reads | Modifies | Writes |
|---|---|---|---|---|
| `write_settings(map_id, field, value)` | one field on one map | `cloud_state.settings.raw` | entry 0's `[map_id][field]` | `SETTINGS.0..N + .info` |
| `write_schedule(new_slots)` | full slot list | `cloud_state.schedule.version` | bumps `v` by 1 | `SCHEDULE.0..N + .info` |
| `write_ai_human_enabled(enabled)` | bool | nothing | n/a | `AI_HUMAN.0` (single chunk, no info needed) |

All three are async and call into the lock + `cloud_client.write_chunked_key`. They return `bool` (cloud accepted: code 0).

### Layer 3 — entity layer

**Optimistic-update + revert-on-failure** pattern, applied uniformly:

```
1. Save old_value = coordinator.data.<field>
2. coordinator.data = dataclasses.replace(coordinator.data, <field>=new_value)
3. self.async_write_ha_state()                          ← instant UI feedback
4. ok = await coordinator.write_<domain>(...)
5. if ok:
       (next 10-min refresh confirms; no visible change)
   else:
       coordinator.data = dataclasses.replace(..., <field>=old_value)
       self.async_write_ha_state()                      ← revert UI
       persistent_notification.create(
           f"Dreame A2 Mower: {entity_name} write rejected",
           notification_id=f"dreame_a2_write_fail_{entity_id}",
       )
```

Notification id is per-entity so repeated failures replace rather than stack.

## Decoder revision (urgent — pre-existing bug)

The current `protocol/schedule.py` decoder hardcodes 7-byte records and breaks the moment a Zone or Edge plan exists. Verified live 2026-05-08 against user's app-added Zone Wed 16:00 + Edge Sat 19:00.

**Variable-length record format:**

```
Byte 0:  0xAA — start sentinel
Byte 1:  length (total record size: 7 for All-area, 8 for Zone, 9 for Edge)
Byte 2:  high nibble = weekday (1=Mon..7=Sun)
         low nibble  = action_type (0=All-area, 1=Zone, 2=Edge)
Byte 3:  time_lo
Byte 4:  high nibble = ??? (TBD — not time-related)
         low nibble  = time_hi  →  time_min = byte[3] | ((byte[4] & 0x0F) << 8)
Byte 5:  reserved (always 0x00 in observed All-area data; non-zero in Zone/Edge)
Byte 6:  zone_id (Zone records: zone_id; All-area: 0xED end sentinel)
Byte 7:  Zone records: 0xED end sentinel; Edge records: extra byte (likely contour_id)
Byte 8:  Edge records only: 0xED end sentinel
```

Action codes verified live:
- `0` = All-area mowing
- `1` = Zone mowing (zone_id at byte 6)
- `2` = Edge mowing (zone_id-or-contour_id at bytes 5-7; exact split TBD; capture as opaque `extra_bytes`)

`SchedulePlan` dataclass gains:
- `zone_id: int | None` (set for Zone/Edge plans, None for All-area)
- `extra_bytes: bytes` (opaque trailing payload — Edge has 3 bytes; preserved for byte-identical round-trip even before we fully decode)

Encoder mirrors: emit variable-length records sized by action_type. Tests use the live data fixtures from your slot 0 (now containing All-area + Zone + Edge plans).

## Entity layer changes

### Naming principle: app-mirror

**Always match the Dreame app's labels.** Users will operate via both the app and HA; matching names removes a translation step. Where app names are localized, English forms are canonical (the user's app is set to English; future i18n is a separate translation-key concern).

### SETTINGS-driven entities

| Cloud field | Current entity name | New entity name | Notes |
|---|---|---|---|
| `mowingHeight` | "Mowing height" | **Mowing Height** | per-map; cm |
| `mowingDirection` | "Mowing direction" | **Mowing Direction** | select; degrees |
| `mowingDirectionMode` | "Mowing direction mode" | **Mowing Pattern** | select renamed; options become **Striped / Crisscross / Chequerboard** (verify mapping at deploy) |
| `cutterPosition` | "Cutter position" | (keep generic) | TBD app mapping; varies per map (1 vs 2). Likely related to cutterBias action 503. |
| `cutterPositionHeight` | "Cutter height" | (keep generic) | TBD app mapping |
| `edgeMowingNum` | "Edge passes" | (keep, app term TBD) | int 1-3 |
| `edgeMowingAuto` | "Edge mowing auto" | **Automatic Edge Mowing** | bool |
| `edgeMowingSafe` | "Edge mowing safe" | **Safe Edge Mowing** | bool |
| `edgeMowingObstacleAvoidance` | "Edge mowing obstacle avoidance" | **Obstacle Avoidance on Edges** | bool |
| `edgeMowingWalkMode` | "Edge walk mode" | (keep generic) | TBD app mapping; walk_0/walk_1 |
| `obstacleAvoidanceEnabled` | "Obstacle avoidance enabled" | **LiDAR Obstacle Recognition** | bool |
| `obstacleAvoidanceHeight` | "Obstacle avoidance height" | **Obstacle Avoidance Height** | cm |
| `obstacleAvoidanceDistance` | "Obstacle avoidance distance" | **Obstacle Avoidance Distance** | cm |
| `obstacleAvoidanceSensitivity` | "Obstacle avoidance sensitivity" | (keep generic) | TBD; doesn't map cleanly per user |
| `obstacleAvoidanceAi` | "Obstacle avoidance AI" (single number 0-255) | **3 separate switches** (see below) | bitfield split |

### `obstacleAvoidanceAi` split

Current: one `number` entity with raw int 0-255 (user's value: `7 = 0b111`).

New: three switches matching the app's three toggles under "AI Obstacle Recognition":
- `switch.dreame_a2_mower_ai_recognition_humans` — "AI Obstacle Recognition: Humans"
- `switch.dreame_a2_mower_ai_recognition_animals` — "AI Obstacle Recognition: Animals"
- `switch.dreame_a2_mower_ai_recognition_objects` — "AI Obstacle Recognition: Objects"

Bit positions confirmed by toggling each in app once + observing cloud value:
- bit 0 (0x01) = humans
- bit 1 (0x02) = animals
- bit 2 (0x04) = objects

Each switch writes the OR-combined int back via `write_settings(map_id, "obstacleAvoidanceAi", new_int)`.

The original `DreameA2ObstacleAvoidanceAiNumber` entity is **removed** (entity-id rename — orphan cleanup per `feedback_entity_rename_orphan` memory pattern).

### AI_HUMAN switch

`switch.dreame_a2_mower_ai_human_detection` is renamed to **"Capture Photos AI Obstacles"** matching the app. Existing entity_id stays for backwards-compat (the unique_id is unchanged).

### SCHEDULE — custom Lovelace card

New file: `dashboards/cards/dreame-a2-schedule-card.js` (vanilla JS, no build step).

**Card layout** (single card on the Work Logs view's Schedule tab):

1. **Slot tabs** at top: "Spr & Sum Schedule" / "Aut & Win Schedule" (cloud-side names; integration's defaults map fills empty names per the existing dashboard fix).
2. **Active-slot weekly grid** (Mon..Sun columns, hourly rows):
   - Existing plans rendered as colored 2-hour blocks per the app's convention: green=All-area, blue=Zone, red=Edge
   - All plans take 2h regardless of action; matches app behavior (not lawn-size-aware)
   - Tap empty slot → "Add Plan" modal
   - Tap existing plan → "Edit / Delete" modal, fields pre-filled
3. **"Add Plan" / "Edit Plan" modal:**
   - Action select: All-area / Zone / Edge
   - Time picker (15-min granularity)
   - Days-of-week multi-select
   - Zone select (for Zone/Edge actions): populated from `cloud_state.maps_by_id[active_map_id].mowing_zones` (zone_id + name)
   - Save validates client-side: refuse if proposed plan overlaps an existing plan in any selected weekday (mirroring the app's same constraint)
4. **"Apply changes" / "Discard" footer** when there are unsaved local edits

**Data flow:**

- Card reads from `sensor.dreame_a2_mower_schedule_count.attributes.slots` (already exposes the per-plan structure post-decoder-revision)
- On Save: card calls `dreame_a2_mower.set_schedule_plans` service with `{slot_id, plans: [{time_min, weekday_mask, action_type, zone_id?, extra_bytes?}, ...]}`
- Service handler delegates to `coordinator.write_schedule(new_slots)`
- On success: cloud refresh updates the sensor attrs; card re-renders from sensor
- On failure: persistent_notification + the unsaved local state is preserved so the user can retry

**Why "set the whole slot" not "add/delete one plan":**

The cloud's atomic unit IS the slot blob (`SCHEDULE.0` is one JSON object holding all slots' all plans). Per-plan mutations require server-side RMW which doesn't exist. Card-side full-slot replace is simpler than service-side multi-call orchestration.

**Patrol Logs forward-prep:** the same card scaffold supports a future "Patrol Logs" tab when patrol-schedule data semantics are known. Card's slot-tabs layout extends naturally.

## Failure handling

Three layers:

| Layer | Detection | Action | User-visible |
|---|---|---|---|
| Network / auth | `cloud_client` raises | LOG warning; do NOT revert local optimistic state (next 10-min refresh reconciles) | persistent_notification "cloud unreachable" (transient) |
| Cloud rejects | `code != 0` in response | LOG response body; revert local state to pre-write value | persistent_notification with cloud's `msg` field |
| Silent rejection | refresh shows different value than what we wrote | LOG warning ("apparent silent rejection"); adopt cloud's value as authoritative | (no extra notification — the cloud's value is what stands) |

Notification IDs are per-entity (`dreame_a2_write_fail_{entity_id}`) so repeated failures replace rather than stack. Notifications auto-dismiss when the user clicks them.

## Tests

**Unit (synchronous):**

- `tests/protocol/test_schedule.py` — variable-length decoder fixture from live data: original 3 All-area plans + Zone Wed 16:00 + Edge Sat 19:00. Encoder round-trip byte-identical. New tests: bad length byte, unsupported action_type, malformed extra_bytes.
- `tests/protocol/test_cloud_chunker.py` (NEW) — `cloud_client.write_chunked_key` chunking math at boundaries (0, 1023, 1024, 1025, 2049 chars). Mocked HTTP returns success / 10007 / 80001 / network-error.
- `tests/integration/test_coordinator_writes.py` (NEW) — `write_settings` / `write_schedule` / `write_ai_human_enabled` with stubbed `cloud_state` and stubbed `cloud_client`. Verifies lock acquisition, RMW correctness, rollback on failure.

**Integration (async):**

- `tests/integration/test_optimistic_writes.py` (NEW) — one number entity, one switch, the AI_HUMAN switch. Verifies optimistic update + revert-on-failure + persistent_notification creation.
- Concurrent-write test: two near-simultaneous entity writes serialize via the lock; second sees the first's mutated state.

**Live probes** (kept in `/tmp/`, not shipped):

- `probe_schedule_write.py`, `probe_ai_human_write.py`, `probe_writable_surface.py`, `probe_batch_write.py` — established harness for Phase 2/3 + future debugging. Reference docs link to them.

## Migration / rollout

- **Single PR, single release** (`v1.0.2a1`). Splitting feels safer but actually creates more transitional states — the placeholder removal touches all 15 entities at once, so partial migration is messier than a clean swap.
- Version-bump rationale: alpha counter resets to signal a meaningful capability shift; matches `feedback_hacs_version_ladder` (avoid 9→10 boundary issues).
- Bundled `dashboards/cards/dreame-a2-schedule-card.js` deployed via SCP same as `dashboard.yaml`. Add a `lovelace_resources` reference in `dashboard.yaml`.
- Entity rename for `obstacleAvoidanceAi` (number → 3 switches): orphan cleanup per `feedback_entity_rename_orphan` memory pattern. Release notes call this out + provide the WS command for orphan removal.

**Release note headline:** "Integration is now read/write. SETTINGS, AI_HUMAN, and SCHEDULE entities mutate the cloud when changed." Plus the orphan-cleanup instruction for `number.dreame_a2_mower_obstacle_avoidance_ai`.

## Documentation

**Updates to existing docs:**

- `docs/research/g2408-research-journal.md` §"SCHEDULE blob format" — replace the fixed-7-byte description with the variable-length format. Add Zone/Edge byte layouts. Update action-code catalogue (0/1/2 confirmed).
- `docs/research/g2408-research-journal.md` §"Systemic finding (set_properties vs setDeviceData)" — flip from "blocked" to "resolved". Document the working endpoint, the 1024-char chunk cap, the field-name asymmetry (GET accepts `model`, SET requires `data`).
- `docs/TODO.md` — close: "Capture SETTINGS write wire format", "AI_HUMAN write capability", "Capture SCHEDULE write dispatch path". Keep open: MAP write (Phase 2 marker). Keep open: capture EdgeMaster/Mowing Efficiency cloud field correlations (post-cloud-discovery re-verification).

**New docs:**

- `docs/research/cloud-write-reference.md` — general "how to read/write cloud state on g2408" reference. Sections: empty-batch read, `setDeviceData` write, chunking rules, list of confirmed-writable keys, list of TBD-or-unsafe keys, the systemic 80001 (MIoT) vs 0 (chunked-batch) distinction, code pointers (`cloud_client.set_batch_device_datas` and `coordinator.write_*`).

## Out of scope (filed as separate TODO entries)

1. **Phase 2: MAP write** — boundary / mowing-zone / exclusion-zone editing without walking the mower. Needs auto-backup mechanism + safety review.
2. **Phase 3: other chunked keys** (FBD_NTYPE, M_PATH, OTA_INFO, TASKID, prop.s_*) — per-key probing as use cases arise.
3. **EdgeMaster / Mowing Efficiency cloud-field correlation** — re-verify whether these surface in cloud SETTINGS post-cloud-discovery (historical "BT-only" claim predates that work).
4. **Customize Mowing Direction page** — beyond `mowingDirection` + `mowingDirectionMode`, the app's per-map page may have additional state we haven't captured.
5. **`cutterPosition` semantics** — varies per map (1 vs 2); investigate via `cutterBias` action 503 correlation.
6. **TBD entity name confirmations** — `cutterPosition`, `cutterPositionHeight`, `edgeMowingNum`, `edgeMowingWalkMode`, `obstacleAvoidanceSensitivity`. As app counterparts get identified, update entity names.

## Spec / plan / version footprint

- This spec: `docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
- Implementation plan to follow: `docs/superpowers/plans/2026-05-08-cloud-write-integration.md`
- Targeted release: `v1.0.2a1`
