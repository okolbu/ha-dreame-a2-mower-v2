# Observability surface — F6

This file documents what the integration self-reports about itself.
Use it to debug or to file a clean bug report.

## Diagnostic sensors

| Entity | Default state | What |
|---|---|---|
| `sensor.dreame_a2_mower_novel_observations` | enabled | Count of unfamiliar protocol shapes seen this process. Attribute `observations` lists each: category (`property` / `value` / `event` / `key`), detail string, first-seen unix timestamp. |
| `sensor.dreame_a2_mower_data_freshness` | disabled | Age in seconds of the OLDEST tracked field. Attributes: per-field age in seconds (`{field_name}_age_s`). |
| `sensor.dreame_a2_mower_api_endpoints_supported` | disabled | Count of routed-action opcodes the cloud accepted. Attributes: `accepted`, `rejected_80001`, `error` lists by op key. |
| `sensor.dreame_a2_mower_archived_sessions_count` | enabled | (from F4) total archived session entries on disk. |

The disabled sensors can be enabled per-entity via Settings → Devices & Services → Dreame A2 Mower → Entities. They are off by default because the freshness map is chatty (every field change triggers an attribute update) and the endpoint log is an opt-in protocol-debugging surface.

## Log prefixes that mean something

| Prefix | Triggers when |
|---|---|
| `[NOVEL/property]` | A property push arrived for an `(siid, piid)` slot the integration doesn't recognize. Once per slot per process. |
| `[NOVEL/value]` | A property push arrived with a value the integration has never seen for a known slot. Once per `(siid, piid, value)` per process. |
| `[NOVEL_KEY/session_summary]` | The OSS session-summary JSON contained a key not in the parser's schema. Once per key per process. |

All three are emitted at WARNING level. They are gated on a process-scoped registry — a single restart re-arms every gate, so the integration re-flags drift after upgrades.

## Downloading a diagnostics dump

Settings → Devices & Services → Dreame A2 Mower → "Download Diagnostics".

The dump is JSON with these top-level keys:

| Key | Contents |
|---|---|
| `config_entry` | Config entry data with creds redacted (`username`, `password`, `token`, `did`, `mac`) |
| `state` | Snapshot of `MowerState` at dump time (every field as native types) |
| `capabilities` | Fixed g2408 capability flags (constants, not runtime-resolved) |
| `novel_observations` | List from the registry: `[{category, detail, first_seen_unix}]` |
| `freshness` | Per-field last-updated unix timestamps: `{field_name: ts}` |
| `endpoint_log` | Cloud-RPC accept/reject map: `{routed_action_op=N: "accepted" | "rejected_80001" | "error"}` |
| `recent_novel_log_lines` | Tail of NOVEL log lines (capped at 200) |

Attach the dump to bug reports; everything sensitive is redacted.

## Operational notes

- Registry and log buffer are process-scoped. A HA restart drops them. This is intentional — version upgrades may add new known shapes, and re-arming the novelty gates surfaces leftover drift.
- The novel-observation registry caps at 200 entries. On a chronically-misconfigured device, additional novel tokens are tracked by the underlying watchdog (so the same token still won't log twice) but won't appear in the sensor attribute list.
- Schema fingerprints live in `observability/schemas.py` as Python constants, not on disk. A drift in a config file would itself be a worse failure mode than drift in the code.
- Per-field freshness is computed from `MowerState` dataclass fields — a field is "stamped" only when its value actually changes, so a stale-but-correct field reads as old, while a noisy field that re-publishes the same value every tick stays at its first-real-change timestamp.
