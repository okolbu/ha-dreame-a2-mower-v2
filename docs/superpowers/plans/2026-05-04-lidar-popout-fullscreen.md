# LiDAR Card Fullscreen Popout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LiDAR card open a controllable WebGL fullscreen overlay (drag-orbit / zoom / splat slider, all preserved) instead of letting HA's stock more-info dialog show only a static image.

**Architecture:** The card itself becomes the fullscreen presenter — no HA more-info override. An "expand" button on the inline card opens a fixed-position overlay containing a fresh `<dreame-a2-lidar-card>` instance, configured with `_embedded` so the second instance doesn't render its own expand button (avoids recursion). User settings already persist to `localStorage`, so the overlay instance picks up the same splat / map flags / Z. Dismissal: ESC key, close button, or backdrop click. As a second trigger path, the card subscribes to the existing `dreame_a2_mower_lidar_fullscreen` event bus message that the `show_lidar_fullscreen` service already fires (the dashboard markdown currently notes "the card doesn't listen for the event yet" — that becomes false after this work).

**Tech Stack:** Vanilla JS / WebGL 1.0 (no framework, no test runner). All changes inside `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`.

**Verification approach:** No JS test infrastructure exists in this project. Verification is `node --check` for syntax + manual browser testing on the user's HA instance after install. Manual checks are listed as concrete steps.

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js` | Modify | Add expand button to inline shadow DOM; new `_openFullscreen` / `_closeFullscreen` methods; HA event subscription; `_embedded` config flag to suppress the expand button on the overlay instance. |
| `dashboards/mower/dashboard.yaml` | Modify | Replace the markdown note that says the card "doesn't listen for the event yet". |
| `custom_components/dreame_a2_mower/manifest.json` | Modify | Bump `version` from `1.0.0a64` to `1.0.0a65`. |
| `docs/TODO.md` | Modify | Strike the "LiDAR popout" entry; add a one-line `## Recently shipped` bullet for a65. |

---

## Task 1: Add expand button + fullscreen overlay

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`

**Why:** This is the primary user path — the inline card needs an obvious in-card control to open the popout. The overlay hosts a fresh card instance whose own expand button is suppressed via the new `_embedded` flag.

- [ ] **Step 1.1: Read the current `setConfig` shadow-DOM template**

```bash
sed -n '274,346p' /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```

You'll be inserting a new `<button class="expand">` inside the `.controls` div and a new `.expand` style rule. Match the existing inline-style + shadow-DOM pattern.

- [ ] **Step 1.2: Add the expand button + close-overlay styles to `setConfig`**

In `setConfig` (around line 274–346), make three edits:

**Edit A — add styles inside the `<style>` block (after the existing `.map-controls input[type=range]` rule):**

```css
        .expand {
          display: ${this._embedded ? "none" : "flex"};
          align-items: center; justify-content: center;
          position: absolute; top: 8px; right: 8px;
          width: 28px; height: 28px;
          background: rgba(20, 20, 20, 0.55);
          border: none; border-radius: 8px;
          color: #ddd; cursor: pointer;
          backdrop-filter: blur(2px);
          font-family: var(--primary-font-family, sans-serif); font-size: 16px;
          padding: 0;
        }
        .expand:hover { background: rgba(40, 40, 40, 0.75); }
        .close-overlay {
          display: ${this._embedded ? "flex" : "none"};
          align-items: center; justify-content: center;
          position: absolute; top: 12px; right: 12px;
          width: 36px; height: 36px;
          background: rgba(20, 20, 20, 0.65);
          border: none; border-radius: 10px;
          color: #fff; cursor: pointer;
          font-family: var(--primary-font-family, sans-serif); font-size: 22px;
          padding: 0; z-index: 2;
        }
        .close-overlay:hover { background: rgba(60, 60, 60, 0.85); }
```

**Edit B — add the buttons inside `<div class="wrap">` (immediately before `<div class="status">`):**

```html
          <button class="expand" type="button" title="Expand to fullscreen" aria-label="Expand">⛶</button>
          <button class="close-overlay" type="button" title="Close (ESC)" aria-label="Close">×</button>
```

**Edit C — at the end of `setConfig`, after the existing `this._flipYCb = ...` lookups, add the new element refs and bind the expand handler:**

```javascript
    this._expandBtn = this.shadowRoot.querySelector(".expand");
    this._closeOverlayBtn = this.shadowRoot.querySelector(".close-overlay");
    if (this._expandBtn && !this._embedded) {
      this._expandBtn.addEventListener("click", () => this._openFullscreen());
    }
    if (this._closeOverlayBtn && this._embedded) {
      this._closeOverlayBtn.addEventListener("click", () => this._dispatchOverlayClose());
    }
```

- [ ] **Step 1.3: Plumb `_embedded` through the constructor and `setConfig`**

In the constructor (around lines 211–237), add at the end (after `this._dpr = window.devicePixelRatio || 1;`):

```javascript
    this._embedded = false;       // set true on the overlay instance
    this._overlayEl = null;       // root <div> when this instance owns an overlay
    this._overlayCard = null;     // the embedded child card inside _overlayEl
    this._overlayKeyHandler = null;
    this._eventUnsub = null;      // HA event-bus unsubscriber (Task 3)
```

In `setConfig`, immediately after `this._config = config || {};` (around line 240), add:

```javascript
    this._embedded = Boolean(this._config._embedded);
```

Don't put `_embedded` in the user-facing YAML schema; the underscore prefix marks it as an internal flag the inline card sets when spawning the overlay instance.

- [ ] **Step 1.4: Implement `_openFullscreen` and `_dispatchOverlayClose`**

Add these methods to the class, before the closing brace (e.g., right after `_draw()`):

```javascript
  // Open a fullscreen overlay containing a fresh, embedded copy of this
  // card. The overlay instance reads the same localStorage settings, so
  // the user's current splat / map / flip preferences carry over.
  _openFullscreen() {
    if (this._overlayEl) return;  // already open
    // Persist current state so the overlay instance starts identical.
    try { this._saveSaved(); } catch (_) { /* ignore */ }

    const overlay = document.createElement("div");
    overlay.className = "dreame-lidar-fullscreen-overlay";
    overlay.style.cssText = [
      "position:fixed",
      "inset:0",
      "background:rgba(0,0,0,0.92)",
      "z-index:99998",
      "display:flex",
      "align-items:center",
      "justify-content:center",
      "padding:0",
    ].join(";");

    // Backdrop click dismisses (but only when the click lands on the
    // overlay div itself, not a child card element).
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) this._closeFullscreen();
    });

    const card = document.createElement("dreame-a2-lidar-card");
    // Force the embedded card to fill the viewport rather than the
    // inline 1:1 aspect-ratio default.
    card.style.cssText = "width:100vw;height:100vh;display:block";
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    // Configure the embedded card with the same user-facing options
    // plus _embedded:true so its own expand button is suppressed and
    // its close-overlay button is shown.
    const cfg = Object.assign({}, this._config, { _embedded: true });
    card.setConfig(cfg);
    if (this._hass) card.hass = this._hass;

    // Bridge the embedded card's close request up to us.
    card.addEventListener("dreame-lidar-overlay-close", () => this._closeFullscreen());

    // ESC dismisses.
    this._overlayKeyHandler = (e) => {
      if (e.key === "Escape") this._closeFullscreen();
    };
    document.addEventListener("keydown", this._overlayKeyHandler);

    this._overlayEl = overlay;
    this._overlayCard = card;
  }

  _closeFullscreen() {
    if (!this._overlayEl) return;
    if (this._overlayKeyHandler) {
      document.removeEventListener("keydown", this._overlayKeyHandler);
      this._overlayKeyHandler = null;
    }
    try {
      this._overlayEl.remove();
    } catch (_) { /* ignore */ }
    this._overlayEl = null;
    this._overlayCard = null;
  }

  // Embedded instances dispatch this when their close button is hit;
  // the parent listener in _openFullscreen converts it to a teardown.
  _dispatchOverlayClose() {
    this.dispatchEvent(new CustomEvent("dreame-lidar-overlay-close", { bubbles: true, composed: true }));
  }
```

- [ ] **Step 1.5: Make the embedded card's `.wrap` fill its parent**

The inline card uses `aspect-ratio: 1 / 1` so it stays square in a Lovelace grid. The embedded card needs to fill the viewport instead. Update the existing `.wrap` rule inside the `<style>` block in `setConfig`:

Find:
```css
        .wrap { position: relative; width: 100%; aspect-ratio: 1 / 1; background: ${this._config.background || "#111"}; border-radius: var(--ha-card-border-radius, 12px); overflow: hidden; }
```

Replace with:
```css
        .wrap { position: relative; width: 100%; ${this._embedded ? "height: 100%;" : "aspect-ratio: 1 / 1;"} background: ${this._config.background || "#111"}; border-radius: ${this._embedded ? "0" : "var(--ha-card-border-radius, 12px)"}; overflow: hidden; }
```

The embedded variant uses `height: 100%` so it fills the overlay (which itself is `100vh`), and drops the rounded corners since it's fullscreen.

- [ ] **Step 1.6: Syntax-check the modified file**

Run:
```bash
node --check /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```
Expected: no output (success).

If `node` isn't available, fall back to a minimal Python AST-style check via parsing as text — at minimum verify the file still ends with `customElements.define(...)` and `window.customCards.push(...)`:
```bash
tail -10 /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```

- [ ] **Step 1.7: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "lidar-card: expand button + fullscreen overlay (close on ESC / backdrop / button)"
```

---

## Task 2: Subscribe to the `dreame_a2_mower_lidar_fullscreen` HA event

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`

**Why:** The `dreame_a2_mower.show_lidar_fullscreen` service already fires `dreame_a2_mower_lidar_fullscreen` on the HA event bus (see `services.py:177`). Having the card listen lets users open the overlay from automations, shortcuts, scripts, etc., without needing to be on the dashboard.

- [ ] **Step 2.1: Add subscription in `set hass`**

Find `set hass(hass)` (around lines 348–362). The current implementation re-fires `_fetchAndRender` once on first hass attach. Extend it to also subscribe to the bus on first attach. Replace the body with:

```javascript
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded && this._config && this._status) {
      this._fetchAndRender();
    }
    // Subscribe once per element instance — `_eventUnsub` is the unsub
    // function returned by hass.connection.subscribeEvents. Embedded
    // overlay instances don't subscribe (they'd fight the inline card
    // for the open-overlay action; only the inline card opens overlays).
    if (!this._embedded && !this._eventUnsub && hass && hass.connection
        && typeof hass.connection.subscribeEvents === "function") {
      hass.connection
        .subscribeEvents(() => this._openFullscreen(), "dreame_a2_mower_lidar_fullscreen")
        .then((unsub) => { this._eventUnsub = unsub; })
        .catch((ex) => console.error("[dreame-a2-lidar-card] subscribe failed", ex));
    }
  }
```

- [ ] **Step 2.2: Tear down the subscription on disconnect**

The class currently has no `disconnectedCallback`. Add one immediately after `connectedCallback` (around line 377):

```javascript
  disconnectedCallback() {
    // Drop the HA event subscription so a navigated-away card doesn't
    // still try to spawn overlays. `set hass` re-subscribes on
    // reconnect (because `_eventUnsub` is null again).
    if (this._eventUnsub) {
      try { this._eventUnsub(); } catch (_) { /* ignore */ }
      this._eventUnsub = null;
    }
    // Also clean up the overlay if the card was popped out and the
    // user navigates away.
    if (this._overlayEl) {
      try { this._closeFullscreen(); } catch (_) { /* ignore */ }
    }
  }
```

- [ ] **Step 2.3: Syntax check**

```bash
node --check /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```
Expected: no output.

- [ ] **Step 2.4: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "lidar-card: open fullscreen on dreame_a2_mower_lidar_fullscreen event"
```

---

## Task 3: Update dashboard markdown + bump manifest + TODO

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`
- Modify: `custom_components/dreame_a2_mower/manifest.json`
- Modify: `docs/TODO.md`

**Why:** The dashboard markdown currently says the card "doesn't listen for the event yet" — that line becomes wrong after Task 2. Striking the TODO entry + bumping the version + a Recently-shipped bullet keep the project's housekeeping consistent with prior releases.

- [ ] **Step 3.1: Update the dashboard markdown**

In `dashboards/mower/dashboard.yaml`, find the LiDAR view's markdown card (around lines 169–176):

```yaml
      - type: markdown
        content: |
          The card supports drag-to-orbit, wheel-to-zoom, and a slider
          for splat size. To open in 3D fullscreen, click the card and
          use HA's standard fullscreen toggle.

          A `dreame_a2_mower.show_lidar_fullscreen` service exists
          for future hooks; the card doesn't listen for the event yet.
```

Replace with:

```yaml
      - type: markdown
        content: |
          The card supports drag-to-orbit, wheel-to-zoom, and a slider
          for splat size. Tap the **⛶** button (top-right of the card)
          for an interactive fullscreen view; ESC, the **×** button, or
          a backdrop click dismisses.

          The `dreame_a2_mower.show_lidar_fullscreen` service also opens
          the fullscreen overlay — useful from automations or scripts.
```

- [ ] **Step 3.2: Bump the manifest version**

In `custom_components/dreame_a2_mower/manifest.json`:

```diff
-  "version": "1.0.0a64"
+  "version": "1.0.0a65"
```

- [ ] **Step 3.3: Strike the TODO entry and add a Recently-shipped bullet**

In `docs/TODO.md`:

(a) Remove the entire `### LiDAR popout: make the modal controllable like the inline card` section (it's directly above the "Dashboard: replicate the Dreame app's contextual button transitions" entry).

(b) Update the "Last updated:" line near the top from `Last updated: 2026-05-04 (v1.0.0a64).` to `Last updated: 2026-05-04 (v1.0.0a65).`

(c) Update the "Recently shipped" heading from `## Recently shipped (a52 → a64)` to `## Recently shipped (a52 → a65)`.

(d) Add a new bullet at the TOP of the Recently-shipped list:

```markdown
- **v1.0.0a65** — LiDAR card grows an in-card **⛶** expand button that
  opens an interactive fullscreen overlay (drag-orbit / wheel-zoom /
  splat slider / map underlay all work, settings carry over via
  `localStorage`). Dismisses on ESC, the **×** button, or backdrop
  click. Card also subscribes to `dreame_a2_mower_lidar_fullscreen`
  so the existing `show_lidar_fullscreen` service triggers the same
  overlay from automations.
```

- [ ] **Step 3.4: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add dashboards/mower/dashboard.yaml custom_components/dreame_a2_mower/manifest.json docs/TODO.md
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "v1.0.0a65: LiDAR card fullscreen overlay shipped"
```

---

## Task 4: Manual browser verification on the live HA instance

**Why:** No JS test runner exists. Real verification has to happen in a browser against the user's HA install. The plan can't run this for the user, but it documents the exact steps so the user (or controller) can confirm before tagging the release.

The card's static-path serve happens once per HA boot; HACS-installed updates land in `/config/custom_components/dreame_a2_mower/www/`. After the version bump in Task 3, HACS will offer a65 as an update; the file on disk gets replaced, but the **browser cache** is the load-bearing piece — Lovelace caches custom-card JS aggressively.

- [ ] **Step 4.1: Push and tag (deferred to Task 5; do verification first if doing in-session)**

If verifying before tagging, you can scp the file directly to the HA host without bumping the manifest, so the user can test before HACS is involved. Skip if running the full release flow.

```bash
HA_HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
HA_USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
HA_PASS=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$HA_PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js \
  "$HA_USER@$HA_HOST:/homeassistant/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js"
```

- [ ] **Step 4.2: Ask the user to hard-refresh their dashboard**

In the user's browser on the Mower → LiDAR view: Cmd+Shift+R (Mac) or Ctrl+Shift+R (Win/Linux). This bypasses the HTTP cache and re-fetches the card JS.

- [ ] **Step 4.3: User-driven manual checks (record results)**

Have the user verify each of:

1. **⛶ button visible** in the top-right corner of the LiDAR card.
2. **Click ⛶** → fullscreen overlay opens, point cloud renders, controls visible top-left, **×** button visible top-right, no ⛶ button on the overlay.
3. **Drag** in the overlay → orbits the camera. **Wheel** → zooms.
4. **Splat slider / map toggle** in the overlay work.
5. **ESC key** → overlay dismisses, inline card resumes.
6. **Click ×** → overlay dismisses.
7. **Click backdrop** (away from the card) → overlay dismisses.
8. **Reopen ⛶** → settings (splat / map flags) match what was set last time.
9. **Developer Tools → Services → `dreame_a2_mower.show_lidar_fullscreen` → CALL** → overlay opens automatically.
10. **Navigate away from the LiDAR view** while overlay is open → overlay closes cleanly (no orphaned div in `document.body`).

Record any failure as a NEEDS_CONTEXT or BLOCKED status before proceeding to Task 5.

---

## Task 5: Tag, push, GitHub release

**Files:** none (git operations only)

**Why:** Memory entry "Every version needs a GitHub Release" — HACS reads Releases. Per the same memory: this fork publishes alpha versions WITHOUT `--prerelease` (so HACS picks them up as Latest). a64 hit this exact pitfall — don't repeat.

- [ ] **Step 5.1: Push main**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower push origin main
```

- [ ] **Step 5.2: Tag**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower tag -a v1.0.0a65 -m "v1.0.0a65: LiDAR card fullscreen overlay"
git -C /data/claude/homeassistant/ha-dreame-a2-mower push origin v1.0.0a65
```

- [ ] **Step 5.3: Create the GitHub Release WITHOUT `--prerelease`**

```bash
gh release create v1.0.0a65 \
  --repo okolbu/ha-dreame-a2-mower \
  --title "v1.0.0a65 — LiDAR card fullscreen overlay" \
  --notes "$(cat <<'EOF'
## LiDAR card grows a fullscreen popout

The bundled WebGL LiDAR card now has an in-card **⛶** expand button
that opens an interactive fullscreen overlay. The overlay supports
the same controls as the inline card: drag-orbit, wheel-zoom, splat
slider, soft splats, map underlay (incl. Z + flip). User settings
persist via `localStorage` so the overlay starts where the inline
card left off.

Dismiss with ESC, the **×** button, or a backdrop click.

The existing `dreame_a2_mower.show_lidar_fullscreen` service now
opens the same overlay — useful from automations and scripts.
EOF
)"
```

- [ ] **Step 5.4: Verify the release is NOT prerelease**

```bash
gh release view v1.0.0a65 --repo okolbu/ha-dreame-a2-mower --json tagName,isPrerelease,isDraft
```
Expected: `isPrerelease: false`. If it accidentally got marked prerelease, run:
```bash
gh release edit v1.0.0a65 --repo okolbu/ha-dreame-a2-mower --prerelease=false
```

- [ ] **Step 5.5: Trigger HACS to refresh (optional, but useful — saves the user from waiting an hour)**

```bash
HA_HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
HA_TOKEN=$(sed -n 4p /data/claude/homeassistant/ha-credentials.txt)
python3 - <<PY
import json, websocket, sys
ws = websocket.create_connection(f"ws://{open('/data/claude/homeassistant/ha-credentials.txt').read().splitlines()[0]}:8123/api/websocket")
hello = json.loads(ws.recv())
ws.send(json.dumps({"type":"auth","access_token":open('/data/claude/homeassistant/ha-credentials.txt').read().splitlines()[3]}))
print("auth:", json.loads(ws.recv()).get("type"))
ws.send(json.dumps({"id":1,"type":"hacs/repository/refresh","repository":"1222724230"}))
print("refresh:", json.loads(ws.recv()))
ws.close()
PY
```

---

## Self-review checklist

1. **Spec coverage**: TODO entry asked for "wire the popout to the same WebGL card JS so the modal view supports the same gestures and controls." Plan delivers via the embedded-card overlay (Task 1) + HA event subscription (Task 2). The TODO also mentioned "a custom HA `more-info` dialog" as an alternative — explicitly NOT pursued because (a) it's brittle to override built-in domain dialogs and (b) the in-card expand button is a more discoverable UX. Documented in the architecture summary.
2. **Placeholder scan**: every code step includes the actual code; every command includes the actual command. The `node --check` fallback step explicitly tells the implementer what to do if `node` is missing.
3. **Type consistency**: `_embedded` flag used identically in constructor / `setConfig` / event guard / disconnect. `_overlayEl` and `_overlayCard` are the only state variables holding the overlay; tracked uniformly. CustomEvent name `dreame-lidar-overlay-close` is used at both dispatch (embedded card) and listen (inline card) sites.
4. **No JS tests**: explicitly called out in the plan header. Verification is `node --check` + manual browser flow in Task 4 with a 10-step user-driven checklist.
