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

## Cutting a release that HACS will actually see

Use `tools/release.sh` — it guards against every failure mode that has
historically broken HACS visibility for this repo. Examples:

```bash
tools/release.sh                   # auto-bump (a80 → a81)
tools/release.sh 1.0.0a99          # explicit version
tools/release.sh --notes "blah"    # custom release notes
tools/release.sh --notes-file NOTES.md
```

The script enforces:

1. **Bump → commit → tag → push tag → `gh release create`** in that
   order, on the same commit. Tagging a commit that doesn't have the
   bumped `manifest.json` makes HACS show the new version but install
   the wrong code.
2. **No `--prerelease`** — this user's HACS doesn't have "Show beta"
   enabled, and prereleases are invisible to it. (Verified across a52
   onward — every alpha tag in this repo is `isPrerelease: false`.)
3. **`--latest`** explicitly — guards against a stale "Latest"
   pointer left over from a `--prerelease` edit.
4. **Post-flight verification** — checks that the manifest at the tag
   matches the version, the release isn't draft/prerelease, and
   `/releases/latest` points at the new tag. The script aborts with a
   clear error if any of these mismatch.
5. **Triggers HACS' WebSocket refresh** on the local HA host so the
   new release shows up in HACS within seconds, not on its 25-min
   background poll.

### Manual diagnosis if HACS still hides a release

```bash
# 1. Is the release actually visible to GitHub's "latest" API?
gh api repos/{owner}/{repo}/releases/latest --jq '.tag_name, .prerelease, .draft'

# 2. Is the manifest at the tag bumped?
gh api repos/{owner}/{repo}/contents/custom_components/dreame_a2_mower/manifest.json?ref=vX.Y.ZaNN \
  --jq .content | base64 -d | jq .version

# 3. What does HACS think the available version is?
#    (Run with HA host reachable and an LLAT in $LLAT.)
python3 -c "
import json, websocket
ws = websocket.create_connection('ws://10.0.0.30:8123/api/websocket')
ws.recv()
ws.send(json.dumps({'type':'auth','access_token':'$LLAT'}))
ws.recv()
ws.send(json.dumps({'id':1,'type':'hacs/repositories/list'}))
for r in json.loads(ws.recv())['result']:
    if 'ha-dreame-a2-mower' in (r.get('full_name') or '').lower():
        print(r.get('installed_version'), '→', r.get('available_version'))
"

# 4. If GitHub looks correct but HACS shows the old version, force a refresh:
python3 -c "
import json, websocket
ws = websocket.create_connection('ws://10.0.0.30:8123/api/websocket')
ws.recv()
ws.send(json.dumps({'type':'auth','access_token':'$LLAT'}))
ws.recv()
ws.send(json.dumps({'id':1,'type':'hacs/repositories/list'}))
target = next(r for r in json.loads(ws.recv())['result']
              if 'ha-dreame-a2-mower' in (r.get('full_name') or '').lower())
ws.send(json.dumps({'id':2,'type':'hacs/repository/refresh','repository':target['id']}))
print(ws.recv())
"
```
