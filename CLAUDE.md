# Dreame A2 Mower — agent instructions

## Fact discipline (load-bearing)

This repo has had repeated incidents where the agent regenerated debunked
claims, lost track of which facts were wire-verified vs presumed, and let
documentation drift week after week. The cause is always the same: a
finding got recorded in prose but not in any structured place the next
session would find. This rule exists to stop that.

### When the rule fires

You MUST update an inventory file in the same response as any of:

- Observing a new fact about a protocol surface (wire shape, value
  semantics, emission trigger, encoding detail) — whether from a probe
  log, a cloud dump, an app screenshot, or an apk decompile.
- Retracting or correcting a prior claim, including one you wrote
  yourself earlier in the same session.
- Verifying that an integration entity reads from the source it claims to
  (or noticing that the source has changed).
- Adding, renaming, or removing an integration entity (any HA platform
  file: switch / sensor / select / number / binary_sensor / camera /
  button — coordinator is excluded).

### What to record

For protocol facts: `custom_components/dreame_a2_mower/inventory.yaml`.
For integration handling: `custom_components/dreame_a2_mower/entity-inventory.yaml`.

Append a record under the entry's `verifications:` list. Required fields:

```yaml
verifications:
  - date: "<YYYY-MM-DD>"            # today, from runtime context
    status: verified | partial | presumed | retracted
    claim: "one-line statement of what's true (or what was retracted)"
    evidence: "<log_file>@<rough-ts>" | "app-screenshot:<name>" | "apk:<ref>" | omit if status=presumed
    retracts: "<prior claim text>"   # required when status=retracted
    reason: "<why retracted>"        # required when status=retracted
```

Also update `status.last_seen` to today's date.

### The honesty constraint

**Never invent an evidence pointer.** If you cannot point at a real probe
log, screenshot, or apk reference, the status is `presumed`, not
`verified`. Recording a `presumed` claim is better than no record;
recording a `verified` claim without evidence is worse than no record
because the next session will trust it.

For retractions, the only required honesty is that `retracts:` quotes
the prior claim that's being withdrawn — not a paraphrase. Grep for
the prose in the entry's `semantic:` block and flag it for the user if
it needs rewording.

### Where this rule does NOT apply

- Refactors that don't change wire understanding or entity sources.
- File renames, comment edits, formatting changes.
- Test additions.
- Changes inside `coordinator.py` (too broad — gating it would create
  noise; the rule applies to the entity *definitions* in the platform
  files, not to the orchestrator).

If you're unsure whether the rule applies, default to recording. A stray
`presumed` entry is recoverable; a missed verification is not.

### Convenience shortcuts

- `/verify-fact <surface-key> claim="..." evidence="..." [status=...]` —
  same shape, less typing. Use when there's a single discrete fact.
- `/retract <surface-key> retracts="..." reason="..."` — shortcut for
  the retraction case.

These slash commands are not required; the rule is the load-bearing
part. Use Edit/Write directly when natural.

### Provenance / status taxonomy

| Status | Means |
|---|---|
| `verified` | direct evidence cited — wire capture, screenshot, or apk reference |
| `partial` | decoded with known gaps (e.g., 3 of 4 bytes understood) |
| `presumed` | hypothesis only; no evidence yet |
| `retracted` | prior claim withdrawn; the record exists so the claim isn't regenerated |

### Why this matters

When the agent ships a finding in prose only, the next session reads the
prose without the structure that says how confident it is. Three weeks
later, the prose has been overwritten or buried, the agent re-derives
the original wrong claim, and the user has to debunk it again. The
inventory entries are the only thing that survives that cycle — they
keep prior claims (including retracted ones) addressable, so the agent
doesn't have to rediscover what was already learned.

---

## Per-map naming convention (load-bearing)

All per-map entities are namespaced under the integration's prefix. The
load-bearing rule is in `_devices.py:map_device_info`:

```python
display_name = f"{DEFAULT_NAME} {suffix}"   # "Dreame A2 Mower Map 1"
```

HA composes friendly_name and entity_id from the device's `name:` and
the entity's `_attr_name:`. With `has_entity_name=True`:

- friendly_name = `<device_name> <entity_name>` (e.g., "Dreame A2 Mower Map 1 EdgeMaster")
- entity_id = `<platform>.<slug(device_name)>_<slug(entity_name)>`
  (e.g., `switch.dreame_a2_mower_map_1_edgemaster`)

### Rules

1. **NEVER name a per-map sub-device without the integration prefix.**
   Bare `"Map 1"` / `"Map 2"` produces entity_ids like `select.map_1_*`
   that collide with other integrations' generic Map entities. The
   `f"{DEFAULT_NAME} {suffix}"` form is mandatory.

2. **NEVER set `_attr_name = f"{map_name} ..."`** on a per-map entity
   class. With `has_entity_name=True` HA already prepends the device
   name. Manually prefixing produces doubled friendly_names like
   "Dreame A2 Mower Map 1 Dreame A2 Mower Map 1 Edge walk mode" and
   doubled entity_id slugs.

   The correct form is `_attr_name = "<entity name only>"` (e.g.,
   `"Edge walk mode"`, `"EdgeMaster"`, `"Base"`).

3. **Parent-device entities** use `mower_device_info()` which sets the
   device name to `DEFAULT_NAME` ("Dreame A2 Mower"). Entity_ids are
   `<platform>.dreame_a2_mower_<key>`. Same `_attr_name` rule —
   entity-name only, no manual prefix.

4. **User-renamed maps** (the Dreame app's custom map name) flow
   through to the device name automatically — the prefix is still
   applied, so a map renamed "Front Yard" gets device name
   "Dreame A2 Mower Front Yard" and entity_ids stay namespaced.

### Why this matters

Pre-2026-05-14 the per-map device names were bare `"Map N+1"` and
entity_ids were `<platform>.map_N_<key>`. That collided with other
integrations and made the per-map / parent-device prefixes look
unrelated in the UI. We tried to fix it incrementally (per-map
sub-device split, then double-prefix bug fix) and ended up with three
parallel naming schemes in the same registry. The convention above
is the consolidated answer; tests in
`tests/integration/test_per_map_entity_names.py` and
`tests/integration/test_devices_helpers.py` pin it.

### Per-map entities are static-at-setup (by design)

Each platform's `async_setup_entry` builds per-map entities by looping
`coordinator.cloud_state.maps_by_id` **once**, so a map discovered after
setup gets no entities until the config entry is reloaded. This is
intentional for a single-user deployment (maps rarely change; reload is a
fine workaround — see `feedback_no_migration_overengineering`). Do **not**
add dynamic per-map `async_add_entities` machinery without a real need.
Note the device side *is* dynamic: `_device_sync._sync_map_subdevices`
adds/removes per-map devices on every cloud refresh, so a new map's device
appears immediately — only its entities wait for a reload.

---

## Coordinator structure (load-bearing)

The mower coordinator lives in
`custom_components/dreame_a2_mower/coordinator/` as a **package**, not a
single file. Decomposed 2026-05-15 from a 4997-LOC `coordinator.py`
monolith (see
`docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md`
and the matching plan).

Each submodule owns one concern. When adding a new method, place it in
the submodule whose concern it matches:

| File | LOC | Concern |
|---|---|---|
| `__init__.py` | 76 | Class assembly + public re-exports |
| `_core.py` | 787 | `__init__`, `_async_update_data`, properties, `_init_cloud`, `_init_mqtt` |
| `_refreshers.py` | 782 | All `_refresh_*` cloud-refresh cycles |
| `_session.py` | 667 | Restore / persist / finalize / replay / work-log render |
| `_mqtt_handlers.py` | 667 | MQTT message routing, state-update glue, event_occured, MAPL apply |
| `_property_apply.py` | 591 | Module-level helpers + constants — pure `(siid, piid, value) → MowerState` functions |
| `_writes.py` | 543 | `write_*` (settings, schedule, ai_human, action) + `dispatch_action` + `start_mowing_*` |
| `_lidar_oss.py` | 480 | LiDAR archive + cloud-OSS fetch handlers |
| `_device_sync.py` | 395 | Map sub-device registry sync + emergency-stop banner + `_fire_*` lifecycle events |
| `_cloud_state.py` | 366 | `cloud_state` apply to MowerState + map fetch / persist |
| `_rendering.py` | 287 | Live-map render, live-trail re-render, last-session-obstacle overlay |
| `_wifi_archive.py` | 246 | WiFi heatmap archive refresh + matcher plumbing |

### Mixin pattern

Each submodule defines exactly one mixin class
(`_<ConcernName>Mixin`). `DreameA2MowerCoordinator` (in `__init__.py`)
inherits from all of them plus `DataUpdateCoordinator[MowerState]`. All
`self.foo` references work via Python's MRO.

**Only `_CoreMixin` owns `__init__`** — it's the sole site that
assigns `self._foo = ...` for shared private state. Every other mixin
is a pure method container. Don't override `__init__` in any other
mixin; don't write to a new `self._<attr>` without first adding it to
`_CoreMixin.__init__`.

### Public-import preservation

`from .coordinator import DreameA2MowerCoordinator` (and
`apply_property_to_state`, `_BLOB_SLOTS`, `_SUPPRESSED_SLOTS`,
`S2P2_NOTIFICATION_MAP`, `_project_north_east`) resolve through
`coordinator/__init__.py`'s re-exports. Tests and entity platforms
keep their imports unchanged.

### Cross-mixin type hints

A mixin method may call into another mixin's method (e.g., `_apply_mapl`
in `_MqttHandlersMixin` schedules `self._render_main_view()` which
lives in `_RenderingMixin`). Use `TYPE_CHECKING` blocks to satisfy
static analysis:

```python
if TYPE_CHECKING:
    from ._rendering import _RenderingMixin
```

At runtime this is a no-op; the MRO dispatches.

### Don't

- Don't add a new method to `_property_apply.py` unless it's a pure
  `MowerState → MowerState` function with no side effects. Side-effect
  methods belong in one of the mixins.
- Don't bring back a `coordinator.py` single file. The package is the
  contract.
- Don't add a `Mixin` to the inheritance list without first creating
  the file and registering its mixin class. Static analyzers and
  Python's MRO both need the class defined before the inheritance
  list references it.

---

## Refresher cadence (load-bearing)

Cloud polling is consolidated onto one full-state timer plus a few
fast/slow specialists. Do **not** re-add per-slot CFG/MIHIS timers — they
were removed in the 2026-05-25 refresher consolidation
(`docs/superpowers/specs/2026-05-25-refresher-consolidation-design.md`).

| Timer | Interval | Why separate |
|---|---|---|
| `_refresh_cloud_state` | 2 min | Full state: cfg, mihis, mapl, settings, maps, props. Ports CFG via `cfg_to_state_updates`, MIHIS + SETTINGS, and active-map via `_apply_mapl(cs.mapl)`. |
| `_refresh_locn` | 60 s | GPS position wants low latency. |
| `_refresh_dock` | 60 s | Dock arrival/departure latency **and** feeds `state_machine.handle_cloud_poll` (cloud_state path does not). |
| `_refresh_net` | 1 h | NET is not part of the full-state fetch. |
| `_refresh_dev` | 6 h | DEV is not part of the full-state fetch. |
| `_poll_slow_properties` | 1 h | s6.3 + s1.5 serial-while-unknown; feeds the state machine. |

`CloudState` does **not** carry `locn`/`dock` — those flow straight to
`MowerState` via their 60 s timers. The CFG→MowerState port lives in the pure
`coordinator/_property_apply.py:cfg_to_state_updates` helper, which never nulls
a field for an absent CFG key and never emits `pre_mowing_height_mm` /
`pre_edgemaster` (those are owned by the s6.2 push, `property_mapping.py`).

---

## Cloud client structure (load-bearing)

The cloud client lives in
`custom_components/dreame_a2_mower/cloud_client/` as a **package**, not a
single file. Decomposed 2026-05-20 from a monolithic `cloud_client.py`
(B1d split).

Each submodule owns one concern. When adding a new method, place it in
the submodule whose concern it matches:

| File | Concern |
|---|---|
| `__init__.py` | Shell `DreameA2CloudClient`: `__init__` + state, properties, MQTT accessors (`mqtt_host_port`, `mqtt_client_id`, `mqtt_credentials`, `mqtt_topic`), `_ensure_strings`, `disconnect`, mixin assembly, public re-export |
| `_helpers.py` | Shared module-level helpers: `_LOGGER`, `_http_retry`, `_random_agent_id` |
| `_auth.py` | `_AuthMixin`: login (primary + secondary-key refresh-token path) |
| `_discovery.py` | `_DiscoveryMixin`: device discovery (`get_devices`, `get_device_info`, `get_info`, `select_first_g2408`) |
| `_rpc.py` | `_RpcMixin`: transport/RPC — `send`, `request`, `action`, `routed_action`, `send_async`, `action_async`, `get_properties`, `set_property`, `set_properties`, `_api_call`, `_api_call_async`, `get_api_url` |
| `_oss.py` | `_OssMixin`: OSS signed-URL fetch (`get_interim_file_url`, `get_file_url`), WiFi heatmap fetch/list (`fetch_wifi_map`, `list_wifi_candidates`), raw file download (`get_file`) |
| `_batch.py` | `_BatchMixin`: batch device-data primitives (`get_batch_device_datas`, `set_batch_device_datas`, `write_chunked_key`, `get_device_data`, `get_device_property`, `get_device_event`) |
| `_fetchers.py` | `_FetchersMixin`: `fetch_full_cloud_state`, `fetch_cfg`, `fetch_locn`, `fetch_dev`, `fetch_mihis`, `fetch_dock`, `fetch_net`, `fetch_map`, `fetch_mapl`, `set_cfg`, `set_pre` |

### Rules

- One `_<Concern>Mixin` per file; the file name mirrors the concern.
- Only the shell `__init__.py` owns `__init__` — it's the sole site that
  assigns `self._foo = ...` for shared private state. Every other mixin
  is a pure method container.
- Shared module-level helpers (logger, retry, agent-id) live in
  `_helpers.py`; mixin files import from there, not from each other.
- Domain imports use `from ..` (parent package); sibling imports use
  `from .` (this package). Local imports inside method bodies (e.g.
  `from ..protocol.cfg_action import ...`) are fine — they avoid
  circular-import problems and are already established in the codebase.
- The public `DreameA2CloudClient` is assembled and re-exported from
  `cloud_client/__init__.py`. Keep that re-export — callers do
  `from .cloud_client import DreameA2CloudClient`.
- Do NOT reintroduce a single `cloud_client.py`. The package is the
  contract.

---

## Rendering structure (load-bearing)

Map rendering lives in `custom_components/dreame_a2_mower/map_render/` as a
**package** (B4b split, 2026-05-21, from a 1283-LOC `map_render.py`). The camera
platform is a thin entry file with domain-grouped siblings.

### map_render/ package

| File | Concern |
|---|---|
| `__init__.py` | Re-export shim — the public surface only |
| `_geometry.py` | Coord transforms (`_cloud_to_px`, `_renderer_to_px`), `extract_projection`, palette + shared consts (`_DEFAULT_PALETTE`, `_DOCK_RADIUS_PX`, `_OBSTACLE_FILL`, `_OBSTACLE_OUTLINE`) |
| `base_map.py` | `render_base_map` (+ `_composite_polygon`) + mower-icon (`_mower_icon`, `_MOWER_ICON_*`) |
| `main_view.py` | `render_main_view` + pre-start previews (`_render_pre_start_*`, `STRIPE_WIDTH_MM`) |
| `work_log.py` | `render_work_log` (archived-session render) |
| `trail.py` | `render_with_trail` (+ `_TRAIL_LINE_WIDTH`) |

- **Acyclic imports:** `_geometry` ← `base_map` ← {`main_view`, `work_log`,
  `trail`} ← `__init__`. `_geometry` imports nothing internal; never add a
  back-edge.
- A module-level constant used by functions landing in ≥2 modules lives in
  `_geometry.py` (e.g. `_OBSTACLE_FILL`/`_OBSTACLE_OUTLINE`, used by both
  `base_map` and `trail`).
- **Public surface = `__init__.py` re-exports ONLY** the names real callers
  import (`render_base_map`, `render_main_view`, `render_work_log`,
  `render_with_trail`, `extract_projection`, `_DEFAULT_PALETTE`,
  `_OBSTACLE_FILL`, `_OBSTACLE_OUTLINE`, `_cloud_to_px`, `_renderer_to_px`).
  Keep `from ..map_render import …` working. No "just in case" re-exports.
- `render_work_log` calls `render_with_trail` via the package
  (`from . import render_with_trail` inside the function) so test mocks on
  `map_render.render_with_trail` still intercept across the module boundary.
- Do NOT reintroduce a single `map_render.py`. The package is the contract.

### camera platform

`camera.py` is a thin platform entry (`async_setup_entry` + the four
`hass.http.register_view` calls). Entity classes live in domain-grouped
siblings — `_camera_map.py`, `_camera_lidar.py`, `_camera_wifi.py` — and the
four `HomeAssistantView` HTTP endpoints in `_camera_views.py` (B3a flat-sibling
pattern). The platform file imports them all, which keeps
`from …camera import X` working for tests.

---

## Protocol decoder naming (convention)

In `protocol/`, decoder entry points follow a name convention by INPUT SOURCE:

- `decode_*` — decodes a **device/MQTT wire payload** into a dataclass. This
  covers raw binary frames (`decode_s1p1`, `decode_s1p4`, `decode_pcd`,
  `decode_pcd_header` — all take `bytes`) and MQTT property values
  (`decode_s2p51` — takes the parsed property payload, a dict/list).
- `parse_*` — parses a **cloud JSON / batch** structure (dict/str → dataclass).
  Examples: `parse_session_summary`, `parse_schedule_batch`, `parse_settings_batch`.

When adding a new decoder, pick the prefix by source: device/MQTT wire →
`decode_*`, cloud JSON → `parse_*`. (PCD was renamed from `parse_pcd*` to
`decode_pcd*` in B2a to fit this rule.)

---

## Related files

- `custom_components/dreame_a2_mower/inventory.yaml` — wire/protocol truth.
- `custom_components/dreame_a2_mower/entity-inventory.yaml` — integration entity truth.
- `docs/research/inventory/README.md` — schema reference for inventory.yaml.
- `tools/inventory_audit.py` — CI consistency check; run locally before
  shipping a fact-heavy change.
- `.github/workflows/ci.yml` — `inventory-touch-gate` job blocks PRs
  that change protocol or entity definitions without updating the
  corresponding inventory file.
