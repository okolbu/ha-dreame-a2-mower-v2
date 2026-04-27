# Contributing to the Dreame A2 Mower integration

This integration is in active rebuild — see the spec at
`docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`
for the architecture and roadmap.

## Do not commit secrets

`*credentials*`, `*.env`, `*.pem`, `*.key`, `secrets.yaml`, and the
`<config>/dreame_a2_mower/` archive directory are excluded by
`.gitignore`. **Never commit cloud credentials to this repo.** If
you're sharing a debug log or probe capture, redact `username`,
`password`, `token`, `did`, and `mac` first.

The integration's `download_diagnostics` endpoint redacts those
fields automatically when producing diagnostic dumps for support
issues.

## Reporting issues

Use the GitHub issue tracker. For protocol-related bug reports,
please attach:

- The output of `download_diagnostics` (creds redacted automatically).
- Recent HA logs (search for `[NOVEL/...]` or `[EVENT]` prefixes).
- The mower's firmware version (visible in HA's Device page).

## Reverse-engineering contributions

If you're adding decoding support for a newly-observed property,
firmware variant, or message shape:

1. Add an entry to `docs/research/g2408-protocol.md` §2.1 with
   evidence (probe-log line, observed value, timing context).
2. Add a decoder to `protocol/` if the property is a structured
   blob.
3. Add a `MowerState` field with proper §2.1 citation in
   `mower/state.py`.
4. Add an entity descriptor to the appropriate platform.
5. Cite the protocol-doc row in the commit message.
