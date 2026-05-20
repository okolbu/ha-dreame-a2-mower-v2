# `cloud_client.py` Split (B1d) — Design

**Date:** 2026-05-20
**Status:** spec
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Discovery findings:** `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 4
(59-row placement table, module-state scan, 25-importer impact table).

## What this is

The fourth and final source-modifying phase of Block 1. `cloud_client.py`
is a 2287-LOC single-class monolith (`DreameA2CloudClient`, ~60 methods).
B1d splits it into a **mixin package** `cloud_client/`, mirroring the
coordinator decomposition that CLAUDE.md documents as load-bearing.

**Pure structural.** Every method body is relocated verbatim — no logic
change. The public class `DreameA2CloudClient` is re-exported from the
package `__init__.py`, so all 25 importers (verified in discovery § 4.3)
keep their imports unchanged.

## Decisions (user, 2026-05-20)

1. **Granularity:** 7 concern-modules — the discovery's single `_batch.py`
   (17 methods, ~700 LOC mixing generic batch primitives with g2408-specific
   cloud-state APIs) is split into `_batch.py` (generic primitives) +
   `_fetchers.py` (cloud-state read/write APIs).
2. **Scope:** pure structural move only. The ~22 silent-exception swallows
   in `cloud_client.py` were already given logging in B1a (commit `c7b209d`);
   they stay byte-identical here. Fixing them (re-raise / surface instead of
   fallback) is a deferred follow-on, NOT part of B1d.

## Package layout (8 files)

`custom_components/dreame_a2_mower/cloud_client/`

| File | Class | Contents |
|---|---|---|
| `__init__.py` | `DreameA2CloudClient` (shell) | `__init__` (sole `self._*` owner), simple + MQTT-accessor properties, `_ensure_strings`, `disconnect`, the `DREAME_STRINGS` import, public re-export |
| `_helpers.py` | — (module-level) | `_LOGGER`, `_http_retry`, `_random_agent_id` |
| `_auth.py` | `_AuthMixin` | `login` |
| `_discovery.py` | `_DiscoveryMixin` | `_handle_device_info`, `get_devices`, `select_first_g2408`, `get_device_info`, `get_info` |
| `_rpc.py` | `_RpcMixin` | `_api_task`, `_api_call_async`, `_api_call`, `get_api_url`, `send_async`, `send`, `get_properties`, `set_property`, `set_properties`, `action_async`, `action`, `request`, `routed_action` |
| `_oss.py` | `_OssMixin` | `get_interim_file_url`, `get_file_url`, `_download_wifi_object`, `fetch_wifi_map`, `list_wifi_candidates`, `get_file` |
| `_batch.py` | `_BatchMixin` | `get_device_property`, `get_device_event`, `get_device_data`, `get_batch_device_datas`, `set_batch_device_datas`, `write_chunked_key` |
| `_fetchers.py` | `_FetchersMixin` | `fetch_cfg`, `fetch_locn`, `fetch_dev`, `fetch_mihis`, `fetch_dock`, `fetch_net`, `fetch_map`, `fetch_full_cloud_state`, `fetch_mapl`, `set_cfg`, `set_pre` |

### Method → module placement (current line numbers @ HEAD `06b9c01`)

`_helpers.py`: `_http_retry` (L46), `_random_agent_id` (L81).

`__init__.py` (shell class): `__init__` (L118); properties `device_id` (L162),
`mac_address` (L166), `uid` (L176), `model` (L180), `serial_number` (L184),
`country` (L192), `logged_in` (L196), `connected` (L200), `object_name` (L204),
`mqtt_host_port` (L211), `mqtt_client_id` (L230), `mqtt_credentials` (L243),
`mqtt_topic` (L253); `_ensure_strings` (L272); `disconnect` (L2280).

`_auth.py`: `login` (L314).

`_discovery.py`: `_handle_device_info` (L394), `get_devices` (L420),
`select_first_g2408` (L430), `get_device_info` (L460), `get_info` (L510).

`_rpc.py`: `_api_task` (L281), `_api_call_async` (L291), `_api_call` (L299),
`get_api_url` (L306), `send_async` (L536), `send` (L588), `get_properties`
(L673), `set_property` (L680), `set_properties` (L695), `action_async` (L698),
`action` (L721), `request` (L1444), `routed_action` (L2241).

`_oss.py`: `get_interim_file_url` (L746), `get_file_url` (L783),
`_download_wifi_object` (L800), `fetch_wifi_map` (L855), `list_wifi_candidates`
(L1106), `get_file` (L1265). (Nested helpers `_decode_or_none`,
`_decode_candidate` move with their containing methods.)

`_batch.py`: `get_device_property` (L1304), `get_device_event` (L1309),
`get_device_data` (L1314), `get_batch_device_datas` (L1350),
`set_batch_device_datas` (L1360), `write_chunked_key` (L1402).

`_fetchers.py`: `fetch_cfg` (L1530), `fetch_locn` (L1557), `fetch_dev` (L1593),
`fetch_mihis` (L1632), `fetch_dock` (L1664), `fetch_net` (L1704), `fetch_map`
(L1740), `fetch_full_cloud_state` (L1833), `fetch_mapl` (L2067), `set_cfg`
(L2102), `set_pre` (L2204).

## Mechanics

- **Mixin pattern (per CLAUDE.md "Coordinator structure"):** each concern file
  defines exactly one `_<Concern>Mixin` class. The shell
  `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin,
  _BatchMixin, _FetchersMixin)` inherits them all. Python's MRO makes every
  `self.foo` resolve across mixins.
- **Only the shell owns `__init__`** — it is the sole site assigning `self._*`
  state. No mixin defines `__init__` or introduces new `self._<attr>`.
- **Cross-mixin calls** go through `self` (e.g. `_fetchers` → `self.routed_action`
  in `_rpc`, `self.get_batch_device_datas` in `_batch`; `_discovery` →
  `self.request`/`self.login`). Add `TYPE_CHECKING` cross-mixin imports where a
  static analyzer needs the hint, exactly as the coordinator package does.
- **Shared module-level helpers** live in `_helpers.py` (mirrors the
  coordinator's `_property_apply.py`), imported by the mixins that need them.
  `_http_retry` is used by both `_rpc` (`request`, `send`) and `_oss`
  (`get_file`); a dedicated helpers module avoids a circular import with the
  package `__init__`.
- **Shell-class methods** (`_ensure_strings`, properties, `disconnect`) are
  defined directly on the shell and are reachable from every mixin via `self`.
- The old `cloud_client.py` file is replaced by the `cloud_client/` directory.

## Behavior fidelity (the binding constraint)

- Method bodies are moved **verbatim** — identical logic, identical control
  flow, identical (B1a-logged) exception handling.
- **One deliberate fidelity choice:** a single shared `_LOGGER` in `_helpers.py`
  named `custom_components.dreame_a2_mower.cloud_client`, imported everywhere —
  so log-record logger names stay byte-identical to today. (Discovery § 4.2
  suggested per-module loggers; a shared logger is chosen instead to keep the
  refactor behavior-free. The package logger that `NovelLogBuffer` attaches to
  is unaffected either way.)
- No public method is added, removed, renamed, or re-signatured. No swallow is
  un-swallowed.

## Public-import preservation

`from ..cloud_client import DreameA2CloudClient` (and any `from .cloud_client
import ...`) resolve through `cloud_client/__init__.py`'s re-export. Discovery
§ 4.3 confirmed all 25 importers (16 test sites + 9 coordinator/source sites)
use only the public class — 0 break-risk, 0 caller changes.

## Testing

- The existing suite already exercises the public surface heavily:
  `tests/protocol/test_cloud_client_fetch_map.py`, `..._wifi_candidates.py`,
  `..._set_cfg.py`, `test_fetch_full_cloud_state.py`, `test_cloud_chunker.py`,
  plus the integration importers. All must stay green with no edits.
- Add one small guard test (`tests/protocol/test_cloud_client_package.py`):
  assert `from custom_components.dreame_a2_mower.cloud_client import
  DreameA2CloudClient` imports, and that the class exposes the full expected
  public method set (a name list) — so an accidental drop during the move is
  caught.
- Verify the move is faithful: the package imports cleanly, the full suite
  passes, and a spot review confirms relocated bodies match the originals.

## CLAUDE.md update (in scope)

Add a **"Cloud client structure (load-bearing)"** section to
`custom_components/dreame_a2_mower/CLAUDE.md` (parallel to the existing
"Coordinator structure" section): the package layout table, the mixin pattern,
"only the shell owns `__init__`", public re-export, and the shared-`_helpers`
rule — so future methods land in the right module and nobody reintroduces the
monolith.

## Out of scope (deferred)

- **Swallow-bug fixes** — the [bug]-tagged silent-except handlers (discovery
  § 3) stay as-is (already logged by B1a). A separate small cycle can decide
  re-raise-vs-fallback per site.
- **`_oss.py` further split** — `fetch_wifi_map` (248 LOC) + `list_wifi_candidates`
  (156 LOC) make `_oss.py` the largest module (~500 LOC), but it is cohesive
  (all OSS/wifi). Not split now; revisit only if it grows.

## Push discipline

Per the cleanup cadence (P1–P7): commit on `main` with the `audit-b1d:` prefix;
push for traceability. As a pure-structural refactor with the full suite green,
it can ride to `origin/main` and a `release.sh` version bump without a separate
live smoke-gate (the public surface is unchanged), at the user's discretion.
