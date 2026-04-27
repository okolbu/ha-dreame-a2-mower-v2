# Dreame A2 Mower — Home Assistant Integration

> **Status:** Pre-alpha rebuild. The legacy integration at
> [`ha-dreame-a2-mower`](https://github.com/okolbu/ha-dreame-a2-mower)
> remains the working reference until this rebuild reaches feature
> parity. **Do not install yet.**

This is a from-scratch Home Assistant integration for the Dreame A2
(`dreame.mower.g2408`) robotic lawn mower. It is **not a fork** of any
upstream project. Architecture and roadmap are documented at
[`docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`](docs/superpowers/specs/2026-04-27-greenfield-integration-design.md).

## Why a new integration?

The previous integration was a fork of an upstream Dreame vacuum +
multi-mower codebase. Three weeks of reverse-engineering the A2 surfaced
that the A2 shares too little with other Dreame devices for the
multi-model scaffolding to add value. This rebuild keeps only the
g2408-specific code (the wire-codec library and the protocol research)
and reimplements the rest with current HA best practices.

## License

MIT — see `LICENSE`.
