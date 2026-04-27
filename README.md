# Dreame A2 Mower — Home Assistant Integration

A Home Assistant integration for the **Dreame A2** robotic lawn mower
(model `dreame.mower.g2408`). Written from scratch for the A2; **not a
fork** of any upstream project.

## Status

🚧 Pre-alpha rebuild — F1 (Foundation) phase. The integration installs
and exposes the mower's state, battery, and charging status. Action
calls (start/pause/dock) are not yet wired. Full feature parity with
the legacy [`ha-dreame-a2-mower`](https://github.com/okolbu/ha-dreame-a2-mower)
repo is the F7 cutover gate.

## Roadmap

See `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`
for the full spec including the 48-item behavioral parity checklist
that gates cutover.

| Phase | Scope | Status |
|---|---|---|
| F1 | Foundation (this phase) | 🚧 In progress |
| F2 | Core state | ⏳ Pending |
| F3 | Action surface | ⏳ Pending |
| F4 | Settings (mowing + more) | ⏳ Pending |
| F5 | Session lifecycle | ⏳ Pending |
| F6 | Archives + observability | ⏳ Pending |
| F7 | LiDAR + dashboard polish + cutover | ⏳ Pending |

## Architecture

Three-layer stack:

- **`protocol/`** — pure-Python wire codecs (no `homeassistant.*`
  imports). Lifted from legacy verbatim. Tests run in a vanilla
  pytest venv.
- **`custom_components/dreame_a2_mower/mower/`** — typed domain
  layer. `MowerState` dataclass; capability constants; (siid, piid)
  → field mapping. Also no `homeassistant.*` imports.
- **`custom_components/dreame_a2_mower/`** (top level) — HA glue:
  config_flow, coordinator, entity platforms.

## Installation

**Not yet ready for general use.** Install the legacy repo while the
rebuild progresses.

Once F7 lands, install via HACS:

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add this repo's URL with category **Integration**.
3. Restart HA, then add the integration via Settings → Devices &
   Services → Add Integration → "Dreame A2 Mower".

## License

MIT — see `LICENSE`.
