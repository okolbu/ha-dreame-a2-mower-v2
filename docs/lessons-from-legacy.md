# Lessons from the legacy integration

Edge-case handlers, debugging insights, and protocol-doc evidence
extracted from `ha-dreame-a2-mower-legacy` (the legacy repo) as the planner
encounters them during the F1–F7 rebuild. Each entry cites the legacy
file:line plus a one-line rationale.

This doc is populated lazily — entries appear here when an implementer
cribs a non-obvious behavior from legacy code, never preemptively.

## Entries

## F1.4.1: cloud + MQTT client lift

- **Cloud RPC 80001 failure mode** — see legacy `dreame/protocol.py`
  the `_send_command` retry path. On g2408, cloud-side
  `set_properties` / `action` / `get_properties` consistently return
  HTTP code 80001 ("device unreachable") even while MQTT is actively
  pushing telemetry. The integration treats this as expected, not
  an error. Source: `docs/research/g2408-protocol.md` §1.2.
- **OSS download fallback path works** — `get_interim_file_url` +
  signed-URL fetch is the only reliable RPC path on g2408. Used for
  session-summary JSONs and LiDAR PCDs.
- **MQTT topic format** —
  `/status/<did>/<mac-hash>/dreame.mower.g2408/<region>/`. The
  region prefix is from the cloud login (`eu` / `us` / etc.).
