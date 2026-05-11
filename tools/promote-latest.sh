#!/usr/bin/env bash
# Force the highest-version release to be marked Latest (not prerelease).
#
# Use:
#   tools/promote-latest.sh                # auto-detect highest version
#   tools/promote-latest.sh v1.0.5a8       # promote a specific tag
#
# This is a self-healing tool for when GitHub demotes a release to
# Prerelease unexpectedly (recurring pain on this repo). Safe to run
# any time; idempotent.
#
# Behavior:
#   - Picks the latest tag (by version sort, not date) unless one is given.
#   - Removes any prerelease/draft flags.
#   - Forces --latest pointer to that tag.
#   - Verifies the GitHub /releases/latest API returns that tag.
#   - Triggers HACS refresh on the local HA host (port 8123) if reachable.

set -euo pipefail

TAG="${1:-}"

# Resolve tag: argument or highest-version release.
if [[ -z "$TAG" ]]; then
    TAG="$(gh release list --limit 100 --json tagName --jq '.[].tagName' \
        | sort -V | tail -1)"
    if [[ -z "$TAG" ]]; then
        echo "❌ no releases found" >&2
        exit 1
    fi
    echo "Auto-detected highest-version tag: $TAG"
else
    echo "Using explicit tag: $TAG"
fi

# Sanity: the release must exist.
if ! gh release view "$TAG" >/dev/null 2>&1; then
    echo "❌ release $TAG does not exist on GitHub" >&2
    exit 1
fi

# Show current state.
INFO_BEFORE="$(gh release view "$TAG" --json isPrerelease,isDraft)"
echo "Before: $INFO_BEFORE"

# Force flags. The --latest flag implicitly clears prerelease in newer
# gh versions but we set explicitly for compatibility across versions.
gh release edit "$TAG" --prerelease=false --draft=false --latest >/dev/null

# Verify.
INFO_AFTER="$(gh release view "$TAG" --json isPrerelease,isDraft)"
[[ "$(echo "$INFO_AFTER" | jq -r .isPrerelease)" == "false" ]] \
    || { echo "❌ still prerelease after edit"; exit 1; }
[[ "$(echo "$INFO_AFTER" | jq -r .isDraft)" == "false" ]] \
    || { echo "❌ still draft after edit"; exit 1; }

LATEST_TAG="$(gh api repos/{owner}/{repo}/releases/latest --jq .tag_name)"
[[ "$LATEST_TAG" == "$TAG" ]] \
    || { echo "❌ /releases/latest = $LATEST_TAG, expected $TAG"; exit 1; }

echo "After:  $INFO_AFTER"
echo "✅ $TAG is now Latest (isPrerelease=false, isDraft=false)"
echo "   /releases/latest → $LATEST_TAG"

# Best-effort HACS refresh (matches release.sh's behavior).
HA_HOST="${HA_HOST:-10.0.0.30}"
HA_TOKEN_FILE="${HA_TOKEN_FILE:-/data/claude/homeassistant/ha-credentials.txt}"
if [[ -f "$HA_TOKEN_FILE" ]]; then
    TOKEN="$(sed -n '4p' "$HA_TOKEN_FILE")"
    if [[ -n "$TOKEN" ]]; then
        if curl -sf -m 5 -o /dev/null \
            -H "Authorization: Bearer $TOKEN" \
            "http://${HA_HOST}:8123/api/" 2>/dev/null; then
            echo "Triggering HACS refresh on $HA_HOST..."
            # Use the WebSocket-equivalent service if exposed via REST, else skip.
            curl -s -m 10 \
                -H "Authorization: Bearer $TOKEN" \
                -H "Content-Type: application/json" \
                -X POST \
                "http://${HA_HOST}:8123/api/services/hacs/repository/update_all" \
                >/dev/null 2>&1 || true
            echo "  (HACS refresh dispatched best-effort)"
        fi
    fi
fi
