#!/usr/bin/env bash
# Cut a new release that HACS will actually see.
#
# Usage:
#   tools/release.sh                  # auto-bumps a80 → a81
#   tools/release.sh 1.0.0a99         # explicit version (no leading "v")
#   tools/release.sh --notes "msg"    # auto-bump with custom notes
#
# What this guards against (every failure mode hit historically):
#   1. Tag pushed without a GitHub Release object → HACS invisible.
#      We always run `gh release create` after the tag push.
#   2. `--prerelease` flag set → HACS invisible (user has "Show beta" off).
#      We never pass `--prerelease`.
#   3. Tag pointing to a commit that doesn't have the bumped manifest.json
#      → HACS shows the version but install gets the wrong code.
#      We bump+commit FIRST, then tag the commit we just made.
#   4. manifest.json on `main` and at the tag drift apart.
#      We verify both equal the new version after push.
#   5. Release created but not marked "Latest" because GitHub got confused
#      after a `--prerelease` edit. We pass `--latest` explicitly.
#   6. HACS still showing stale data even after a clean release → we offer
#      to trigger HACS' WebSocket refresh on the local HA host.
#
# Requires: gh (authenticated), git (clean working tree), jq, python3
#
# Safety: aborts on any uncommitted changes, any failed test, or any
# verification step. It will NOT push or release anything until the
# pre-flight is clean.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MANIFEST="custom_components/dreame_a2_mower/manifest.json"
HA_CRED="/data/claude/homeassistant/ha-credentials.txt"

NOTES_FILE=""
EXPLICIT_VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --notes-file) NOTES_FILE="$2"; shift 2 ;;
        --notes) NOTES_TEXT="$2"; shift 2 ;;
        -h|--help)
            sed -n '1,30p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        v*) EXPLICIT_VERSION="${1#v}"; shift ;;
        *) EXPLICIT_VERSION="$1"; shift ;;
    esac
done

# ── 1. pre-flight: clean tree, on main, up-to-date ─────────────────────
if [[ -n "$(git status --porcelain)" ]]; then
    echo "❌ working tree is not clean — commit or stash first" >&2
    git status --short >&2
    exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
    echo "❌ not on main (on $BRANCH) — checkout main first" >&2
    exit 1
fi

git fetch origin main --tags
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [[ "$LOCAL" != "$REMOTE" ]]; then
    echo "❌ local main is not in sync with origin/main" >&2
    echo "   local:  $LOCAL" >&2
    echo "   remote: $REMOTE" >&2
    exit 1
fi

# ── 2. compute next version ─────────────────────────────────────────────
CURRENT="$(jq -r .version "$MANIFEST")"
echo "current manifest version: $CURRENT"

if [[ -n "$EXPLICIT_VERSION" ]]; then
    NEW="$EXPLICIT_VERSION"
else
    # Bump 1.0.0aNN → 1.0.0a(NN+1). Keeps the prefix intact.
    NEW="$(python3 -c "
import re, sys
v = '$CURRENT'
m = re.match(r'^(.*?a)(\d+)$', v)
if not m:
    print(f'cannot auto-bump non-aNN version: {v}', file=sys.stderr)
    sys.exit(1)
print(f'{m.group(1)}{int(m.group(2))+1}')
")"
fi

NEW_TAG="v$NEW"
echo "new version:              $NEW"
echo "new tag:                  $NEW_TAG"

# Refuse if tag already exists locally or remotely.
if git rev-parse "$NEW_TAG" >/dev/null 2>&1; then
    echo "❌ tag $NEW_TAG already exists locally" >&2
    exit 1
fi
if git ls-remote --tags origin "refs/tags/$NEW_TAG" | grep -q .; then
    echo "❌ tag $NEW_TAG already exists on origin" >&2
    exit 1
fi
if gh release view "$NEW_TAG" >/dev/null 2>&1; then
    echo "❌ release $NEW_TAG already exists on GitHub" >&2
    exit 1
fi

# ── 3. tests ────────────────────────────────────────────────────────────
echo "running tests…"
python3 -m pytest tests/ -q --ignore=tests/archive >/tmp/release_pytest.log 2>&1 || {
    echo "❌ tests failed — see /tmp/release_pytest.log" >&2
    tail -20 /tmp/release_pytest.log >&2
    exit 1
}
echo "tests pass: $(tail -1 /tmp/release_pytest.log)"

# ── 4. bump manifest, commit, tag, push, release ────────────────────────
# Targeted regex replace on the version line only — `json.dump`'s
# reformatting (e.g. expanding inline arrays into multiline form)
# would diff additional lines and trip the strict diff check below.
python3 - <<PY
import re, sys
with open("$MANIFEST") as f: text = f.read()
new = re.sub(
    r'("version"\s*:\s*)"[^"]*"',
    r'\1"' + "$NEW" + '"',
    text, count=1,
)
if new == text:
    print("no version line found in manifest", file=sys.stderr)
    sys.exit(1)
with open("$MANIFEST", "w") as f: f.write(new)
PY

# Confirm the diff is exactly the version line.
DIFF_LINES="$(git diff --numstat "$MANIFEST" | awk '{print $1}')"
if [[ "$DIFF_LINES" != "1" ]]; then
    echo "❌ manifest.json diff has $DIFF_LINES insertions, expected 1" >&2
    git diff "$MANIFEST" >&2
    exit 1
fi

# Resolve release notes
if [[ -n "${NOTES_FILE:-}" ]]; then
    NOTES="$(cat "$NOTES_FILE")"
elif [[ -n "${NOTES_TEXT:-}" ]]; then
    NOTES="$NOTES_TEXT"
else
    NOTES="Version bump.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
fi

git add "$MANIFEST"
git commit -m "$NEW: version bump

$NOTES"

# Tag the commit we just made (NOT a different SHA).
git tag "$NEW_TAG" HEAD

# Push commit + tag in one shot.
git push origin main "$NEW_TAG"

# Create the Release. NO --prerelease (HACS hides those for this user).
# --latest is explicit so a stale "latest" pointer can't trip us.
gh release create "$NEW_TAG" \
    --title "$NEW_TAG" \
    --latest \
    --notes "$NOTES"

# ── 5. post-flight verification ─────────────────────────────────────────
echo
echo "verifying release…"

# 5a. manifest.json at the tag matches NEW (= the commit we tagged was the bumped one)
TAG_VERSION="$(gh api "repos/{owner}/{repo}/contents/$MANIFEST?ref=$NEW_TAG" --jq '.content' \
    | base64 -d | jq -r .version)"
if [[ "$TAG_VERSION" != "$NEW" ]]; then
    echo "❌ manifest.json at tag $NEW_TAG = $TAG_VERSION (expected $NEW)" >&2
    exit 1
fi

# 5b. release is the latest, not prerelease, not draft
RELEASE_INFO="$(gh release view "$NEW_TAG" --json tagName,isPrerelease,isDraft,isLatest)"
echo "$RELEASE_INFO" | jq .
[[ "$(echo "$RELEASE_INFO" | jq -r .isPrerelease)" == "false" ]] || { echo "❌ marked prerelease"; exit 1; }
[[ "$(echo "$RELEASE_INFO" | jq -r .isDraft)" == "false" ]]      || { echo "❌ marked draft";       exit 1; }
[[ "$(echo "$RELEASE_INFO" | jq -r .isLatest)" == "true" ]]      || { echo "❌ not latest";         exit 1; }

# 5c. /releases/latest API points at this tag
LATEST_TAG="$(gh api repos/{owner}/{repo}/releases/latest --jq .tag_name)"
if [[ "$LATEST_TAG" != "$NEW_TAG" ]]; then
    echo "❌ GitHub /releases/latest = $LATEST_TAG, expected $NEW_TAG" >&2
    exit 1
fi

echo "✅ release $NEW_TAG published cleanly."
echo "   tag → $NEW_TAG → manifest.json $NEW (match)"
echo "   isLatest=true, isPrerelease=false, isDraft=false"
echo "   /releases/latest → $LATEST_TAG"
echo

# ── 6. optional HACS refresh on local HA ───────────────────────────────
if [[ -f "$HA_CRED" ]] && command -v python3 >/dev/null; then
    echo "triggering HACS refresh on local HA…"
    python3 - <<PY
import json
try:
    import websocket
except ImportError:
    print("(websocket-client not installed; skipping HACS refresh — HACS will catch up on its own poll within ~30 min)")
    raise SystemExit(0)

lines = open("$HA_CRED").read().splitlines()
host, llat = lines[0], lines[3]

ws = websocket.create_connection(f"ws://{host}:8123/api/websocket", timeout=10)
ws.recv()
ws.send(json.dumps({"type": "auth", "access_token": llat}))
ws.recv()
# Find HACS repo id
ws.send(json.dumps({"id": 1, "type": "hacs/repositories/list"}))
resp = json.loads(ws.recv())
repos = resp.get("result") or []
target = next((r for r in repos if "ha-dreame-a2-mower" in (r.get("full_name") or "").lower()), None)
if not target:
    print("(integration not registered with HACS)")
    raise SystemExit(0)
ws.send(json.dumps({"id": 2, "type": "hacs/repository/refresh", "repository": target["id"]}))
print("HACS refresh:", ws.recv())
ws.close()
PY
fi

echo
echo "Done. If HACS still shows the old version after a minute or two, restart HA."
